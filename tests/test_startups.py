from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.crawlers.models import CrawlResult
from src.crawlers.startups import StartupAdapter

REFERENCE = datetime(2026, 1, 10, 12, 0, tzinfo=timezone.utc)


class FakeCrawler:
    def __init__(self, response: CrawlResult) -> None:
        self.response = response
        self.calls: list[str] = []

    async def fetch(self, url: str):
        self.calls.append(url)
        return self.response


def test_startup_parse_feed_extracts_name_website_and_founded_date():
    xml = '''
    <rss version="2.0">
      <channel>
        <item>
          <title>Nova Labs</title>
          <link>https://example.com/startups/1</link>
          <description>AI systems for logistics</description>
          <website>https://novalabs.example</website>
          <location>San Francisco</location>
          <foundDate>2020-06-01</foundDate>
          <source>Public Startup Feed</source>
        </item>
      </channel>
    </rss>
    '''

    adapter = StartupAdapter()
    records = adapter.parse_feed(xml, reference_time=REFERENCE)
    assert len(records) == 1
    startup = records[0]
    assert startup.name == "Nova Labs"
    assert startup.source_url == "https://example.com/startups/1"
    assert startup.website == "https://novalabs.example"
    assert startup.location == "San Francisco"
    assert startup.founded_date == datetime(2020, 6, 1, 0, 0, tzinfo=timezone.utc)
    assert startup.source == "Public Startup Feed"


def test_startup_missing_optional_fields_knows_none_is_used():
    xml = '''
    <rss version="2.0"><channel><item><title>Quiet Foundry</title><link>https://example.com/startups/quiet</link></item></channel></rss>
    '''
    adapter = StartupAdapter()
    records = adapter.parse_feed(xml, reference_time=REFERENCE)
    assert len(records) == 1
    startup = records[0]
    assert startup.description is None
    assert startup.website is None
    assert startup.location is None
    assert startup.founded_date is None
    assert startup.freshness_status == "unknown"


def test_startup_duplicate_url_is_deduplicated():
    xml = '''
    <rss version="2.0"><channel>
      <item><title>Duplicate Startup</title><link>https://example.com/startups/dup</link><pubDate>Sat, 10 Jan 2026 10:00:00 GMT</pubDate><source>Example</source></item>
      <item><title>Duplicate Startup Again</title><link>https://example.com/startups/dup</link><pubDate>Sat, 10 Jan 2026 10:00:00 GMT</pubDate><source>Example</source></item>
    </channel></rss>
    '''
    adapter = StartupAdapter()
    result = adapter.crawl_feed(xml, reference_time=REFERENCE, max_age_hours=24)
    assert len(result.fresh_records) == 1


def test_startup_date_states_are_distinguished():
    xml = '''
    <rss version="2.0"><channel>
      <item><title>Fresh One</title><link>https://example.com/startups/fresh</link><pubDate>Sat, 10 Jan 2026 11:00:00 GMT</pubDate><source>FreshSource</source></item>
      <item><title>Stale One</title><link>https://example.com/startups/stale</link><pubDate>Thu, 08 Jan 2026 12:00:00 GMT</pubDate><source>StaleSource</source></item>
      <item><title>Future One</title><link>https://example.com/startups/future</link><pubDate>Sat, 10 Jan 2026 13:00:00 GMT</pubDate><source>FutureSource</source></item>
      <item><title>No Date One</title><link>https://example.com/startups/missing</link><source>MissingSource</source></item>
    </channel></rss>
    '''
    adapter = StartupAdapter()
    result = adapter.crawl_feed(xml, reference_time=REFERENCE, max_age_hours=24)
    assert len(result.fresh_records) == 1
    assert len(result.stale_records) == 1
    assert len(result.future_records) == 1
    assert len(result.unknown_records) == 1


@pytest.mark.asyncio
async def test_startup_fetch_failure_is_captured():
    adapter = StartupAdapter(
        crawler=FakeCrawler(CrawlResult(requested_url="https://example.com/startups/feed", success=False, error="boom", error_type="http_error"))
    )
    result = await adapter.crawl_startups("https://example.com/startups/feed", reference_time=REFERENCE)
    assert result.fetch_errors
    assert result.fresh_records == []


def test_startup_invalid_source_is_rejected_without_fabrication():
    xml = "<rss><channel><item><title>Broken</title></item></channel></rss>"
    adapter = StartupAdapter()
    records = adapter.parse_feed(xml, reference_time=REFERENCE)
    assert records == []


def test_startup_malformed_entries_are_tolerated():
    xml = '<rss><channel><item><title>Only title</title><link>https://example.com/startups/bad</link><source>Example</source></item><item><description>No title here</description></item></channel></rss>'
    adapter = StartupAdapter()
    records = adapter.parse_feed(xml, reference_time=REFERENCE)
    assert len(records) == 1
    assert records[0].name == "Only title"
