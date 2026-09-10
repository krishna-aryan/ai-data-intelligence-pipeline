from __future__ import annotations

import asyncio
import random
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Callable, Iterable, Mapping

import aiohttp

from .models import CrawlResult


DEFAULT_USER_AGENT = "GraphOneFrontierAtlasCrawler/0.1 (+https://example.com)"
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
RETRYABLE_ERROR_TYPES = {
    "TimeoutError",
    "ClientConnectionError",
    "ClientConnectorError",
    "ClientPayloadError",
    "ConnectionError",
    "ServerTimeoutError",
}


class AsyncHTTPCrawler:
    def __init__(
        self,
        *,
        timeout: float = 10.0,
        max_concurrency: int = 8,
        headers: Mapping[str, str] | None = None,
        max_retries: int = 3,
        base_backoff_seconds: float = 0.5,
        max_backoff_seconds: float = 30.0,
        jitter: bool = True,
        jitter_fn: Callable[[float], float] | None = None,
    ) -> None:
        self.timeout = timeout
        self.max_concurrency = max_concurrency
        self.max_retries = max_retries
        self.base_backoff_seconds = max(0.0, float(base_backoff_seconds))
        self.max_backoff_seconds = max(0.0, float(max_backoff_seconds))
        self.jitter = jitter
        self.jitter_fn = jitter_fn
        self.headers = {
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        if headers:
            self.headers.update(headers)
        self._session: aiohttp.ClientSession | None = None

    async def create_session(self) -> aiohttp.ClientSession:
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.timeout),
            headers=self.headers,
        )
        return self._session

    async def close_session(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None

    def _should_retry(self, result: CrawlResult) -> bool:
        if result.success:
            return False

        if result.status in RETRYABLE_STATUS_CODES:
            return True

        if result.error_type in RETRYABLE_ERROR_TYPES:
            return True

        if result.error_type == "ClientError":
            return True

        return False

    def _parse_retry_after(self, retry_after: str | None) -> float | None:
        if not retry_after:
            return None

        value = retry_after.strip()
        try:
            seconds = float(value)
            if seconds < 0:
                return None
            return min(self.max_backoff_seconds, seconds)
        except ValueError:
            pass

        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError, IndexError):
            return None

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        delta = (parsed - datetime.now(timezone.utc)).total_seconds()
        if delta < 0:
            return 0.0
        return min(self.max_backoff_seconds, delta)

    def _calculate_delay(self, attempt_index: int, result: CrawlResult) -> float:
        retry_after = result.metadata.get("retry_after")
        if result.status == 429 and retry_after is not None:
            try:
                delay = float(retry_after)
            except (TypeError, ValueError):
                delay = None
            if delay is not None:
                return min(self.max_backoff_seconds, max(0.0, delay))

        base_delay = self.base_backoff_seconds * (2 ** attempt_index)
        delay = min(self.max_backoff_seconds, base_delay)

        if not self.jitter:
            return delay

        if self.jitter_fn is not None:
            return max(0.0, self.jitter_fn(delay))

        jitter_amount = random.uniform(0.0, min(delay * 0.25, 1.0))
        return delay + jitter_amount

    def _finalize_result(self, result: CrawlResult, attempts: int) -> CrawlResult:
        metadata = dict(result.metadata)
        metadata["attempts"] = attempts
        metadata["retries"] = max(0, attempts - 1)
        result.metadata = metadata
        return result

    async def fetch_many(
        self,
        urls: Iterable[str],
        *,
        headers: Mapping[str, str] | None = None,
    ) -> list[CrawlResult]:
        urls_list = list(urls)
        if not urls_list:
            return []

        semaphore = asyncio.Semaphore(self.max_concurrency)
        session = await self.create_session()

        try:
            tasks = [self._fetch_with_retries(session, url, semaphore, headers=headers) for url in urls_list]
            return await asyncio.gather(*tasks)
        finally:
            await self.close_session()

    async def fetch(self, url: str, *, headers: Mapping[str, str] | None = None) -> CrawlResult:
        session = await self.create_session()
        try:
            return await self._fetch_with_retries(session, url, asyncio.Semaphore(self.max_concurrency), headers=headers)
        finally:
            await self.close_session()

    async def _fetch_with_retries(
        self,
        session: aiohttp.ClientSession,
        url: str,
        semaphore: asyncio.Semaphore,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> CrawlResult:
        for attempt_index in range(self.max_retries + 1):
            async with semaphore:
                result = await self._fetch_one(session, url, headers=headers)

            if result.success or not self._should_retry(result):
                return self._finalize_result(result, attempt_index + 1)

            if attempt_index >= self.max_retries:
                return self._finalize_result(result, attempt_index + 1)

            delay = self._calculate_delay(attempt_index, result)
            await asyncio.sleep(delay)

        return self._finalize_result(CrawlResult(requested_url=url, success=False, error="Retry loop exhausted"), self.max_retries + 1)

    async def _fetch_one(
        self,
        session: aiohttp.ClientSession,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> CrawlResult:
        try:
            request_headers = dict(self.headers)
            if headers:
                request_headers.update(headers)
            async with session.get(url, headers=request_headers) as response:
                text = await response.text()
                metadata = {
                    "content_type": response.headers.get("Content-Type", ""),
                    "retry_after": self._parse_retry_after(response.headers.get("Retry-After")),
                }
                if 200 <= response.status < 300:
                    return CrawlResult(
                        requested_url=url,
                        status=response.status,
                        success=True,
                        text=text,
                        metadata=metadata,
                    )

                return CrawlResult(
                    requested_url=url,
                    status=response.status,
                    success=False,
                    text=text,
                    error=f"HTTP {response.status}",
                    error_type="http_error",
                    metadata=metadata,
                )
        except asyncio.TimeoutError as exc:
            return CrawlResult(
                requested_url=url,
                status=None,
                success=False,
                error="Request timed out",
                error_type=type(exc).__name__,
                metadata={"retry_after": None},
            )
        except aiohttp.ClientError as exc:
            return CrawlResult(
                requested_url=url,
                status=None,
                success=False,
                error=str(exc),
                error_type=type(exc).__name__,
                metadata={"retry_after": None},
            )
        except Exception as exc:  # pragma: no cover - defensive guard
            return CrawlResult(
                requested_url=url,
                status=None,
                success=False,
                error=str(exc),
                error_type=type(exc).__name__,
                metadata={"retry_after": None},
            )


__all__ = ["AsyncHTTPCrawler"]
