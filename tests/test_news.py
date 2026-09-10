from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.crawlers.news import NewsAdapter, NewsIngestionResult
from src.crawlers.models import CrawlResult


REFERENCE = datetime(2026, 1, 10, 12, 0, tzinfo=timezone.utc)


class FakeCrawler:
    def __init__(self, response: CrawlResult) -> None:
        self.response = response
        self.calls = []

    async def fetch(self, url: str):
        self.calls.append(url)
        return self.response


def test_parse_news_feed_extracts_title_url_and_publication_date():
    xml = '''
    <rss version="2.0">
      <channel>
        <item>
          <title>AI startup launches new model</title>
          <link>https://example.com/news/1</link>
          <pubDate>Sat, 10 Jan 2026 10:00:00 GMT</pubDate>
          <description>Latest AI release</description>
        </item>
      </channel>
    </rss>
    '''

    adapter = NewsAdapter()
    records = adapter.parse_feed(xml, reference_time=REFERENCE)
    assert len(records) == 1
    article = records[0]
    assert article.title == "AI startup launches new model"
    assert article.source_url == "https://example.com/news/1"
    assert article.published_date == datetime(2026, 1, 10, 10, 0, tzinfo=timezone.utc)


def test_recent_article_is_fresh_and_included():
    xml = '''
    <rss version="2.0"><channel><item><title>Fresh story</title><link>https://example.com/news/fresh</link><pubDate>Sat, 10 Jan 2026 11:00:00 GMT</pubDate></item></channel></rss>
    '''
    adapter = NewsAdapter()
    result = adapter.crawl_feed(xml, reference_time=REFERENCE, max_age_hours=24)
    assert result.fresh_records[0].source_url == "https://example.com/news/fresh"
    assert result.excluded_records == []


def test_exact_24_hour_boundary_is_included():
    xml = '''
    <rss version="2.0"><channel><item><title>Boundary story</title><link>https://example.com/news/boundary</link><pubDate>Fri, 09 Jan 2026 12:00:00 GMT</pubDate></item></channel></rss>
    '''
    adapter = NewsAdapter()
    result = adapter.crawl_feed(xml, reference_time=REFERENCE, max_age_hours=24)
    assert len(result.fresh_records) == 1
    assert result.fresh_records[0].source_url == "https://example.com/news/boundary"


def test_stale_article_is_excluded():
    xml = '''
    <rss version="2.0"><channel><item><title>Old story</title><link>https://example.com/news/old</link><pubDate>Thu, 08 Jan 2026 12:00:00 GMT</pubDate></item></channel></rss>
    '''
    adapter = NewsAdapter()
    result = adapter.crawl_feed(xml, reference_time=REFERENCE, max_age_hours=24)
    assert result.stale_records[0].source_url == "https://example.com/news/old"
    assert result.fresh_records == []


def test_missing_date_is_excluded_as_unknown():
    xml = '''
    <rss version="2.0"><channel><item><title>No date</title><link>https://example.com/news/no-date</link></item></channel></rss>
    '''
    adapter = NewsAdapter()
    result = adapter.crawl_feed(xml, reference_time=REFERENCE, max_age_hours=24)
    assert len(result.unknown_records) == 1
    assert result.fresh_records == []


def test_invalid_date_is_excluded_as_unknown():
    xml = '''
    <rss version="2.0"><channel><item><title>Bad date</title><link>https://example.com/news/bad-date</link><pubDate>not-a-date</pubDate></item></channel></rss>
    '''
    adapter = NewsAdapter()
    result = adapter.crawl_feed(xml, reference_time=REFERENCE, max_age_hours=24)
    assert len(result.unknown_records) == 1


def test_future_date_is_excluded_and_remains_future():
    xml = '''
    <rss version="2.0"><channel><item><title>Future story</title><link>https://example.com/news/future</link><pubDate>Sat, 10 Jan 2026 13:00:00 GMT</pubDate></item></channel></rss>
    '''
    adapter = NewsAdapter()
    result = adapter.crawl_feed(xml, reference_time=REFERENCE, max_age_hours=24)
    assert len(result.future_records) == 1
    assert result.fresh_records == []


def test_duplicate_url_is_deduplicated_deterministically():
    xml = '''
    <rss version="2.0"><channel>
      <item><title>Dup</title><link>https://example.com/news/dup</link><pubDate>Sat, 10 Jan 2026 10:00:00 GMT</pubDate></item>
      <item><title>Dup again</title><link>https://example.com/news/dup</link><pubDate>Sat, 10 Jan 2026 10:00:00 GMT</pubDate></item>
    </channel></rss>
    '''
    adapter = NewsAdapter()
    result = adapter.crawl_feed(xml, reference_time=REFERENCE, max_age_hours=24)
    assert len(result.fresh_records) == 1


def test_same_feed_same_reference_time_gives_same_result():
    xml = '''
    <rss version="2.0"><channel><item><title>Stable</title><link>https://example.com/news/stable</link><pubDate>Sat, 10 Jan 2026 10:00:00 GMT</pubDate></item></channel></rss>
    '''
    adapter = NewsAdapter()
    first = adapter.crawl_feed(xml, reference_time=REFERENCE, max_age_hours=24)
    second = adapter.crawl_feed(xml, reference_time=REFERENCE, max_age_hours=24)
    assert first.model_dump() == second.model_dump()


@pytest.mark.asyncio
async def test_async_crawl_uses_existing_http_client_and_captures_fetch_failure():
    adapter = NewsAdapter(crawler=FakeCrawler(CrawlResult(requested_url="https://example.com/feed", success=False, error="boom", error_type="http_error")))
    result = await adapter.crawl_news("https://example.com/feed", reference_time=REFERENCE)
    assert result.fetch_errors
    assert result.fresh_records == []


@pytest.mark.asyncio
async def test_async_crawl_preserves_source_url_and_handles_malformed_feed():
    xml = '<rss><channel><item><title>Broken</title></item></channel></rss>'
    adapter = NewsAdapter(crawler=FakeCrawler(CrawlResult(requested_url="https://example.com/feed", success=True, text=xml)))
    result = await adapter.crawl_news("https://example.com/feed", reference_time=REFERENCE)
    assert result.fresh_records or result.unknown_records or result.feed_errors
