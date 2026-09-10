from __future__ import annotations

import asyncio
from typing import Any, Iterable, Mapping

import aiohttp

from .models import CrawlResult


DEFAULT_USER_AGENT = "GraphOneFrontierAtlasCrawler/0.1 (+https://example.com)"


class AsyncHTTPCrawler:
    def __init__(
        self,
        *,
        timeout: float = 10.0,
        max_concurrency: int = 8,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.timeout = timeout
        self.max_concurrency = max_concurrency
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
            tasks = [self._fetch_one(session, url, semaphore, headers=headers) for url in urls_list]
            return await asyncio.gather(*tasks)
        finally:
            await self.close_session()

    async def fetch(self, url: str, *, headers: Mapping[str, str] | None = None) -> CrawlResult:
        session = await self.create_session()
        try:
            return await self._fetch_one(session, url, asyncio.Semaphore(self.max_concurrency), headers=headers)
        finally:
            await self.close_session()

    async def _fetch_one(
        self,
        session: aiohttp.ClientSession,
        url: str,
        semaphore: asyncio.Semaphore,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> CrawlResult:
        async with semaphore:
            try:
                request_headers = dict(self.headers)
                if headers:
                    request_headers.update(headers)
                async with session.get(url, headers=request_headers) as response:
                    text = await response.text()
                    if 200 <= response.status < 300:
                        return CrawlResult(
                            requested_url=url,
                            status=response.status,
                            success=True,
                            text=text,
                            metadata={"content_type": response.headers.get("Content-Type", "")},
                        )

                    return CrawlResult(
                        requested_url=url,
                        status=response.status,
                        success=False,
                        text=text,
                        error=f"HTTP {response.status}",
                        error_type="http_error",
                        metadata={"content_type": response.headers.get("Content-Type", "")},
                    )
            except asyncio.TimeoutError as exc:
                return CrawlResult(
                    requested_url=url,
                    status=None,
                    success=False,
                    error="Request timed out",
                    error_type=type(exc).__name__,
                )
            except aiohttp.ClientError as exc:
                return CrawlResult(
                    requested_url=url,
                    status=None,
                    success=False,
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
            except Exception as exc:  # pragma: no cover - defensive guard
                return CrawlResult(
                    requested_url=url,
                    status=None,
                    success=False,
                    error=str(exc),
                    error_type=type(exc).__name__,
                )


__all__ = ["AsyncHTTPCrawler"]
