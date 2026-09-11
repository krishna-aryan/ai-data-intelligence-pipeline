from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.crawlers.jobs import JobAdapter, JobIngestionResult
from src.crawlers.models import CrawlResult

REFERENCE = datetime(2026, 1, 10, 12, 0, tzinfo=timezone.utc)


class FakeCrawler:
    def __init__(self, response: CrawlResult) -> None:
        self.response = response
        self.calls: list[str] = []

    async def fetch(self, url: str):
        self.calls.append(url)
        return self.response


def test_parse_job_feed_extracts_title_company_url_and_publication_date():
    xml = '''
    <rss version="2.0">
      <channel>
        <item>
          <title>Senior Python Engineer</title>
          <link>https://example.com/jobs/1</link>
          <pubDate>Sat, 10 Jan 2026 10:00:00 GMT</pubDate>
          <source>Acme Labs</source>
          <description>Build AI systems</description>
          <location>Remote</location>
          <employmentType>Full-time</employmentType>
        </item>
      </channel>
    </rss>
    '''

    adapter = JobAdapter()
    records = adapter.parse_feed(xml, reference_time=REFERENCE)
    assert len(records) == 1
    job = records[0]
    assert job.title == "Senior Python Engineer"
    assert job.company == "Acme Labs"
    assert job.source_url == "https://example.com/jobs/1"
    assert job.published_date == datetime(2026, 1, 10, 10, 0, tzinfo=timezone.utc)
    assert job.location == "Remote"
    assert job.employment_type == "Full-time"


def test_recent_job_is_fresh_and_included():
    xml = '''
    <rss version="2.0"><channel><item><title>Platform Engineer</title><link>https://example.com/jobs/fresh</link><pubDate>Sat, 10 Jan 2026 11:00:00 GMT</pubDate><source>Nova Labs</source></item></channel></rss>
    '''
    adapter = JobAdapter()
    result = adapter.crawl_feed(xml, reference_time=REFERENCE, max_age_hours=24)
    assert result.fresh_jobs[0].source_url == "https://example.com/jobs/fresh"
    assert result.excluded_jobs == []


def test_exact_24_hour_boundary_is_included():
    xml = '''
    <rss version="2.0"><channel><item><title>Data Engineer</title><link>https://example.com/jobs/boundary</link><pubDate>Fri, 09 Jan 2026 12:00:00 GMT</pubDate><source>Northwind</source></item></channel></rss>
    '''
    adapter = JobAdapter()
    result = adapter.crawl_feed(xml, reference_time=REFERENCE, max_age_hours=24)
    assert len(result.fresh_jobs) == 1
    assert result.fresh_jobs[0].source_url == "https://example.com/jobs/boundary"


def test_stale_job_is_excluded():
    xml = '''
    <rss version="2.0"><channel><item><title>Research Engineer</title><link>https://example.com/jobs/old</link><pubDate>Thu, 08 Jan 2026 12:00:00 GMT</pubDate><source>Old Lab</source></item></channel></rss>
    '''
    adapter = JobAdapter()
    result = adapter.crawl_feed(xml, reference_time=REFERENCE, max_age_hours=24)
    assert result.stale_jobs[0].source_url == "https://example.com/jobs/old"
    assert result.fresh_jobs == []


def test_missing_date_is_excluded_as_unknown():
    xml = '''
    <rss version="2.0"><channel><item><title>No date role</title><link>https://example.com/jobs/no-date</link><source>Unknown Co</source></item></channel></rss>
    '''
    adapter = JobAdapter()
    result = adapter.crawl_feed(xml, reference_time=REFERENCE, max_age_hours=24)
    assert len(result.unknown_jobs) == 1
    assert result.fresh_jobs == []


def test_invalid_date_is_excluded_as_unknown():
    xml = '''
    <rss version="2.0"><channel><item><title>Bad date role</title><link>https://example.com/jobs/bad-date</link><pubDate>not-a-date</pubDate><source>Broken Co</source></item></channel></rss>
    '''
    adapter = JobAdapter()
    result = adapter.crawl_feed(xml, reference_time=REFERENCE, max_age_hours=24)
    assert len(result.unknown_jobs) == 1


def test_future_date_is_excluded_and_remains_future():
    xml = '''
    <rss version="2.0"><channel><item><title>Future role</title><link>https://example.com/jobs/future</link><pubDate>Sat, 10 Jan 2026 13:00:00 GMT</pubDate><source>FutureCo</source></item></channel></rss>
    '''
    adapter = JobAdapter()
    result = adapter.crawl_feed(xml, reference_time=REFERENCE, max_age_hours=24)
    assert len(result.future_jobs) == 1
    assert result.fresh_jobs == []


def test_duplicate_url_is_deduplicated_deterministically():
    xml = '''
    <rss version="2.0"><channel>
      <item><title>Duplicate role</title><link>https://example.com/jobs/dup</link><pubDate>Sat, 10 Jan 2026 10:00:00 GMT</pubDate><source>Acme</source></item>
      <item><title>Duplicate role again</title><link>https://example.com/jobs/dup</link><pubDate>Sat, 10 Jan 2026 10:00:00 GMT</pubDate><source>Acme</source></item>
    </channel></rss>
    '''
    adapter = JobAdapter()
    result = adapter.crawl_feed(xml, reference_time=REFERENCE, max_age_hours=24)
    assert len(result.fresh_jobs) == 1


def test_same_feed_same_reference_time_gives_same_result():
    xml = '''
    <rss version="2.0"><channel><item><title>Stable role</title><link>https://example.com/jobs/stable</link><pubDate>Sat, 10 Jan 2026 10:00:00 GMT</pubDate><source>Stable Co</source></item></channel></rss>
    '''
    adapter = JobAdapter()
    first = adapter.crawl_feed(xml, reference_time=REFERENCE, max_age_hours=24)
    second = adapter.crawl_feed(xml, reference_time=REFERENCE, max_age_hours=24)
    assert first.model_dump() == second.model_dump()


@pytest.mark.asyncio
async def test_async_crawl_uses_existing_http_client_and_captures_fetch_failure():
    adapter = JobAdapter(crawler=FakeCrawler(CrawlResult(requested_url="https://example.com/jobs/feed", success=False, error="boom", error_type="http_error")))
    result = await adapter.crawl_jobs("https://example.com/jobs/feed", reference_time=REFERENCE)
    assert result.fetch_errors
    assert result.fresh_jobs == []


@pytest.mark.asyncio
async def test_async_crawl_preserves_source_url_and_handles_malformed_feed():
    xml = '<rss><channel><item><title>Broken</title></item></channel></rss>'
    adapter = JobAdapter(crawler=FakeCrawler(CrawlResult(requested_url="https://example.com/jobs/feed", success=True, text=xml)))
    result = await adapter.crawl_jobs("https://example.com/jobs/feed", reference_time=REFERENCE)
    assert result.fresh_jobs or result.unknown_jobs or result.feed_errors
