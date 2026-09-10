import asyncio
from contextlib import suppress

import pytest
import pytest_asyncio
from aiohttp import web

from src.crawlers.http_client import AsyncHTTPCrawler


@pytest_asyncio.fixture
async def test_server():
    async def ok(request):
        return web.Response(text="ok")

    async def not_found(request):
        return web.Response(status=404, text="missing")

    async def slow(request):
        await asyncio.sleep(0.2)
        return web.Response(text="slow")

    app = web.Application()
    app.router.add_get("/ok", ok)
    app.router.add_get("/not-found", not_found)
    app.router.add_get("/slow", slow)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()

    port = site._server.sockets[0].getsockname()[1]
    base_url = f"http://127.0.0.1:{port}"

    yield base_url

    await runner.cleanup()


@pytest.mark.asyncio
async def test_successful_response(test_server):
    crawler = AsyncHTTPCrawler(timeout=2.0, max_concurrency=2)

    result = await crawler.fetch(f"{test_server}/ok")

    assert result.success is True
    assert result.status == 200
    assert result.text == "ok"


@pytest.mark.asyncio
async def test_http_error_response(test_server):
    crawler = AsyncHTTPCrawler(timeout=2.0, max_concurrency=2)

    result = await crawler.fetch(f"{test_server}/not-found")

    assert result.success is False
    assert result.status == 404
    assert result.error == "HTTP 404"


@pytest.mark.asyncio
async def test_request_exception(test_server):
    crawler = AsyncHTTPCrawler(timeout=0.2, max_concurrency=2)

    result = await crawler.fetch("http://127.0.0.1:1")

    assert result.success is False
    assert result.status is None
    assert result.error is not None


@pytest.mark.asyncio
async def test_multiple_urls(test_server):
    crawler = AsyncHTTPCrawler(timeout=2.0, max_concurrency=4)

    result = await crawler.fetch_many([
        f"{test_server}/ok",
        f"{test_server}/not-found",
        f"{test_server}/ok",
    ])

    assert len(result) == 3
    assert result[0].success is True
    assert result[1].success is False
    assert result[2].success is True


@pytest.mark.asyncio
async def test_concurrency_limit(test_server):
    crawler = AsyncHTTPCrawler(timeout=2.0, max_concurrency=1)
    urls = [f"{test_server}/slow" for _ in range(3)]

    start = asyncio.get_running_loop().time()
    results = await crawler.fetch_many(urls)
    elapsed = asyncio.get_running_loop().time() - start

    assert len(results) == 3
    assert all(item.success for item in results)
    assert elapsed >= 0.5


@pytest.mark.asyncio
async def test_session_resource_cleanup(test_server):
    crawler = AsyncHTTPCrawler(timeout=2.0, max_concurrency=2)

    await crawler.fetch(f"{test_server}/ok")

    assert crawler._session is None
