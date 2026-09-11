from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import pytest

from src.crawlers.models import CrawlResult
from src.live import run_live
from src.models.schemas import SourceInfo, StartupContent, StartupRecord
from src.source_config import SourceConfiguration, SourceConfigurationError, load_source_configuration
from src.storage.repository import SQLiteRecordRepository


class FakeCrawler:
    def __init__(self, responses):
        self.responses = responses

    async def fetch(self, url, *, headers=None):
        response = self.responses.get(url)
        if response is None:
            return CrawlResult(requested_url=url, success=False, error="fixture failure")
        return CrawlResult(requested_url=url, status=200, success=True, text=response)


class FakeProvider:
    async def generate(self, prompt):
        return json.dumps({
            "records": [{
                "recordType": "STARTUP",
                "schemaVersion": "1.0",
                "source": {"name": "Public source", "url": "https://public.example/startup"},
                "content": {"entityName": "OpenAI"},
                "collectedAt": "2026-09-11T12:00:00Z",
            }]
        })


def test_source_configuration_validates_explicit_urls(monkeypatch):
    monkeypatch.setenv("STARTUP_SOURCE_URL", "https://public.example/feed")
    monkeypatch.delenv("PRODUCT_SOURCE_URL", raising=False)
    monkeypatch.delenv("RESEARCH_PAPER_SOURCE_URL", raising=False)
    monkeypatch.delenv("JOB_SOURCE_URL", raising=False)
    monkeypatch.delenv("NEWS_SOURCE_URL", raising=False)

    configuration = load_source_configuration()

    assert configuration.startups == "https://public.example/feed"
    assert configuration.products is None


def test_invalid_source_url_is_rejected(monkeypatch):
    monkeypatch.setenv("STARTUP_SOURCE_URL", "not-a-url")

    with pytest.raises(SourceConfigurationError):
        load_source_configuration()


@pytest.mark.asyncio
async def test_missing_sources_are_skipped_and_no_provider_is_replaced(tmp_path, monkeypatch):
    source_url = "https://public.example/startups.xml"
    feed = "<rss><channel><item><title>OpenAI</title><link>https://public.example/startup</link><pubDate>Fri, 11 Sep 2026 11:00:00 GMT</pubDate></item></channel></rss>"
    monkeypatch.setattr("src.live.build_default_providers", lambda: [])
    result = await run_live(
        configuration=SourceConfiguration(startups=source_url),
        crawler=FakeCrawler({source_url: feed}),
        repository=SQLiteRecordRepository(tmp_path / "live.sqlite3"),
        reference_time=datetime(2026, 9, 11, 12, tzinfo=timezone.utc),
    )

    assert result.fetched_records == 1
    assert set(result.skipped_sources) == {"products", "research_papers", "jobs", "news"}
    assert result.pipeline_result is None
    assert result.extraction_available is False
    assert "no configured Gemini" in result.messages[0]


@pytest.mark.asyncio
async def test_public_source_reaches_pipeline_and_preserves_provenance(tmp_path):
    source_url = "https://public.example/startups.xml"
    feed = "<rss><channel><item><title>OpenAI</title><link>https://public.example/startup</link><pubDate>Fri, 11 Sep 2026 11:00:00 GMT</pubDate></item></channel></rss>"
    repository = SQLiteRecordRepository(tmp_path / "live.sqlite3")
    result = await run_live(
        configuration=SourceConfiguration(startups=source_url),
        crawler=FakeCrawler({source_url: feed}),
        repository=repository,
        provider=FakeProvider(),
        reference_time=datetime(2026, 9, 11, 12, tzinfo=timezone.utc),
    )

    assert result.pipeline_result is not None
    assert result.pipeline_result.succeeded == 1
    saved = repository.get_by_source_url("https://public.example/startup")
    assert saved is not None
    assert str(saved.source.url) == "https://public.example/startup"


@pytest.mark.asyncio
async def test_one_source_failure_does_not_stop_other_configured_sources(tmp_path):
    startup_url = "https://public.example/startups.xml"
    news_url = "https://public.example/news.xml"
    news_feed = "<rss><channel><item><title>Launch</title><link>https://public.example/news</link><pubDate>Fri, 11 Sep 2026 11:00:00 GMT</pubDate></item></channel></rss>"
    calls = []

    async def handler(entity_type, source_url, crawler):
        calls.append(entity_type)
        if entity_type == "startups":
            raise RuntimeError("source unavailable")
        return []

    result = await run_live(
        configuration=SourceConfiguration(startups=startup_url, news=news_url),
        crawler=FakeCrawler({news_url: news_feed}),
        source_handler=handler,
    )

    assert sorted(calls) == ["news", "startups"]
    assert len(result.source_results) == 2
    assert any(item.status == "failed" for item in result.source_results)


@pytest.mark.asyncio
async def test_all_configured_entity_types_are_dispatched():
    configuration = SourceConfiguration(
        startups="https://public.example/startups.xml",
        products="https://public.example/products.xml",
        research_papers="https://public.example/papers",
        jobs="https://public.example/jobs.xml",
        news="https://public.example/news.xml",
    )
    dispatched = []

    async def handler(entity_type, source_url, crawler):
        dispatched.append((entity_type, source_url))
        return []

    await run_live(configuration=configuration, source_handler=handler)

    assert {item[0] for item in dispatched} == {
        "startups", "products", "research_papers", "jobs", "news"
    }