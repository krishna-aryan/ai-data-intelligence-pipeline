import asyncio

import pytest

from src.crawlers.http_client import AsyncHTTPCrawler
from src.crawlers.models import CrawlResult


class RetrySpyCrawler:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    async def fetch(self, url, *, headers=None):
        self.calls += 1
        if self.calls <= len(self.responses):
            return self.responses[self.calls - 1]
        return self.responses[-1]


@pytest.mark.asyncio
async def test_429_then_success_retries_and_succeeds():
    call_count = {"value": 0}

    async def fake_fetch(session, url, *, headers=None):
        call_count["value"] += 1
        if call_count["value"] == 1:
            return CrawlResult(
                requested_url=url,
                status=429,
                success=False,
                text="rate limited",
                error="HTTP 429",
                error_type="http_error",
                metadata={"retry_after": 0.0},
            )
        return CrawlResult(
            requested_url=url,
            status=200,
            success=True,
            text="ok",
            metadata={"content_type": "text/plain"},
        )

    crawler = AsyncHTTPCrawler(timeout=1.0, max_concurrency=1, base_backoff_seconds=0.01, max_backoff_seconds=0.05, jitter=False)
    crawler._fetch_one = fake_fetch

    result = await crawler.fetch("https://example.com/429")

    assert result.success is True
    assert result.metadata["retries"] == 1
    assert call_count["value"] == 2


@pytest.mark.asyncio
async def test_retry_after_header_is_respected(monkeypatch):
    sleep_calls = []

    async def fake_sleep(delay):
        sleep_calls.append(delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    crawler = AsyncHTTPCrawler(timeout=1.0, max_concurrency=1, base_backoff_seconds=0.5, max_backoff_seconds=1.0, jitter=False)
    responses = [
        CrawlResult(
            requested_url="https://example.com",
            status=429,
            success=False,
            text="rate limit",
            error="HTTP 429",
            error_type="http_error",
            metadata={"retry_after": 0.25},
        ),
        CrawlResult(
            requested_url="https://example.com",
            status=200,
            success=True,
            text="ok",
            metadata={"content_type": "text/plain"},
        ),
    ]

    async def fake_fetch_one(session, url, *, headers=None):
        if not responses:
            return CrawlResult(requested_url=url, success=False, error="done")
        return responses.pop(0)

    crawler._fetch_one = fake_fetch_one
    result = await crawler.fetch("https://example.com")

    assert result.success is True
    assert sleep_calls == [0.25]


@pytest.mark.asyncio
async def test_500_then_success():
    calls = {"value": 0}

    async def fake_fetch_one(session, url, *, headers=None):
        calls["value"] += 1
        if calls["value"] == 1:
            return CrawlResult(
                requested_url=url,
                status=500,
                success=False,
                text="server error",
                error="HTTP 500",
                error_type="http_error",
                metadata={"retry_after": None},
            )
        return CrawlResult(
            requested_url=url,
            status=200,
            success=True,
            text="ok",
            metadata={"content_type": "text/plain"},
        )

    crawler = AsyncHTTPCrawler(timeout=1.0, max_concurrency=1, base_backoff_seconds=0.01, max_backoff_seconds=0.05, jitter=False)
    crawler._fetch_one = fake_fetch_one

    result = await crawler.fetch("https://example.com")

    assert result.success is True
    assert result.metadata["retries"] == 1


@pytest.mark.asyncio
async def test_repeated_503_until_max_retries(monkeypatch):
    calls = {"value": 0}

    async def fake_fetch_one(session, url, *, headers=None):
        calls["value"] += 1
        return CrawlResult(
            requested_url=url,
            status=503,
            success=False,
            text="unavailable",
            error="HTTP 503",
            error_type="http_error",
            metadata={"retry_after": None},
        )

    async def fake_sleep(delay):
        return None

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    crawler = AsyncHTTPCrawler(timeout=1.0, max_concurrency=1, max_retries=2, base_backoff_seconds=0.01, max_backoff_seconds=0.05, jitter=False)
    crawler._fetch_one = fake_fetch_one

    result = await crawler.fetch("https://example.com")

    assert result.success is False
    assert result.status == 503
    assert result.metadata["retries"] == 2
    assert calls["value"] == 3


@pytest.mark.asyncio
async def test_connection_failure_then_success(monkeypatch):
    calls = {"value": 0}

    async def fake_fetch_one(session, url, *, headers=None):
        calls["value"] += 1
        if calls["value"] == 1:
            return CrawlResult(
                requested_url=url,
                status=None,
                success=False,
                error="Connection failed",
                error_type="ClientConnectorError",
                metadata={"retry_after": None},
            )
        return CrawlResult(
            requested_url=url,
            status=200,
            success=True,
            text="ok",
            metadata={"content_type": "text/plain"},
        )

    async def fake_sleep(delay):
        return None

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    crawler = AsyncHTTPCrawler(timeout=1.0, max_concurrency=1, base_backoff_seconds=0.02, max_backoff_seconds=0.05, jitter=False)
    crawler._fetch_one = fake_fetch_one

    result = await crawler.fetch("https://example.com")

    assert result.success is True
    assert result.metadata["retries"] == 1


@pytest.mark.asyncio
async def test_timeout_then_success(monkeypatch):
    calls = {"value": 0}

    async def fake_fetch_one(session, url, *, headers=None):
        calls["value"] += 1
        if calls["value"] == 1:
            return CrawlResult(
                requested_url=url,
                status=None,
                success=False,
                error="Request timed out",
                error_type="TimeoutError",
                metadata={"retry_after": None},
            )
        return CrawlResult(
            requested_url=url,
            status=200,
            success=True,
            text="ok",
            metadata={"content_type": "text/plain"},
        )

    async def fake_sleep(delay):
        return None

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    crawler = AsyncHTTPCrawler(timeout=1.0, max_concurrency=1, base_backoff_seconds=0.02, max_backoff_seconds=0.05, jitter=False)
    crawler._fetch_one = fake_fetch_one

    result = await crawler.fetch("https://example.com")

    assert result.success is True
    assert result.metadata["retries"] == 1


@pytest.mark.asyncio
async def test_404_not_retried():
    calls = {"value": 0}

    async def fake_fetch_one(session, url, *, headers=None):
        calls["value"] += 1
        return CrawlResult(
            requested_url=url,
            status=404,
            success=False,
            text="missing",
            error="HTTP 404",
            error_type="http_error",
            metadata={"retry_after": None},
        )

    crawler = AsyncHTTPCrawler(timeout=1.0, max_concurrency=1, max_retries=3, base_backoff_seconds=0.1, jitter=False)
    crawler._fetch_one = fake_fetch_one

    result = await crawler.fetch("https://example.com/not-found")

    assert result.success is False
    assert result.status == 404
    assert result.metadata["retries"] == 0
    assert calls["value"] == 1


@pytest.mark.asyncio
async def test_400_not_retried():
    calls = {"value": 0}

    async def fake_fetch_one(session, url, *, headers=None):
        calls["value"] += 1
        return CrawlResult(
            requested_url=url,
            status=400,
            success=False,
            text="bad request",
            error="HTTP 400",
            error_type="http_error",
            metadata={"retry_after": None},
        )

    crawler = AsyncHTTPCrawler(timeout=1.0, max_concurrency=1, max_retries=3, base_backoff_seconds=0.1, jitter=False)
    crawler._fetch_one = fake_fetch_one

    result = await crawler.fetch("https://example.com/bad")

    assert result.success is False
    assert result.status == 400
    assert result.metadata["retries"] == 0
    assert calls["value"] == 1


@pytest.mark.asyncio
async def test_retry_count_is_recorded():
    calls = {"value": 0}

    async def fake_fetch_one(session, url, *, headers=None):
        calls["value"] += 1
        if calls["value"] < 3:
            return CrawlResult(
                requested_url=url,
                status=503,
                success=False,
                text="temp",
                error="HTTP 503",
                error_type="http_error",
                metadata={"retry_after": None},
            )
        return CrawlResult(
            requested_url=url,
            status=200,
            success=True,
            text="ok",
            metadata={"content_type": "text/plain"},
        )

    async def fake_sleep(delay):
        return None

    crawler = AsyncHTTPCrawler(timeout=1.0, max_concurrency=1, max_retries=3, base_backoff_seconds=0.01, max_backoff_seconds=0.05, jitter=False)
    crawler._fetch_one = fake_fetch_one

    result = await crawler.fetch("https://example.com")

    assert result.success is True
    assert result.metadata["attempts"] == 3
    assert result.metadata["retries"] == 2


@pytest.mark.asyncio
async def test_concurrency_limit_still_works(monkeypatch):
    active = 0
    max_seen = 0

    async def fake_fetch_one(session, url, *, headers=None):
        nonlocal active, max_seen
        active += 1
        max_seen = max(max_seen, active)
        await asyncio.sleep(0.05)
        active -= 1
        return CrawlResult(
            requested_url=url,
            status=200,
            success=True,
            text="ok",
            metadata={"content_type": "text/plain"},
        )

    monkeypatch.setattr(asyncio, "sleep", asyncio.sleep)

    crawler = AsyncHTTPCrawler(timeout=2.0, max_concurrency=2, max_retries=1, base_backoff_seconds=0.01, jitter=False)
    crawler._fetch_one = fake_fetch_one

    results = await crawler.fetch_many(["https://example.com/a", "https://example.com/b", "https://example.com/c"])

    assert len(results) == 3
    assert max_seen <= 2
    assert all(item.success for item in results)
