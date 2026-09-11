from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.crawlers.models import CrawlResult
from src.crawlers.products import ProductAdapter

REFERENCE = datetime(2026, 1, 10, 12, 0, tzinfo=timezone.utc)


class FakeCrawler:
    def __init__(self, response: CrawlResult) -> None:
        self.response = response
        self.calls: list[str] = []

    async def fetch(self, url: str):
        self.calls.append(url)
        return self.response


def test_product_parse_feed_extracts_name_company_and_category():
    xml = '''
    <rss version="2.0">
      <channel>
        <item>
          <title>Orbit AI</title>
          <link>https://example.com/products/1</link>
          <company>Nova Labs</company>
          <description>Workflow automation platform</description>
          <website>https://orbit.example</website>
          <category>Developer Tools</category>
          <pubDate>Sat, 10 Jan 2026 10:00:00 GMT</pubDate>
        </item>
      </channel>
    </rss>
    '''
    adapter = ProductAdapter()
    records = adapter.parse_feed(xml, reference_time=REFERENCE)
    assert len(records) == 1
    product = records[0]
    assert product.name == "Orbit AI"
    assert product.company == "Nova Labs"
    assert product.source_url == "https://example.com/products/1"
    assert product.category == "Developer Tools"
    assert product.website == "https://orbit.example"
    assert product.freshness_status == "fresh"


def test_product_missing_optional_fields_are_none():
    xml = '''
    <rss version="2.0"><channel><item><title>Silent Product</title><link>https://example.com/products/quiet</link></item></channel></rss>
    '''
    adapter = ProductAdapter()
    records = adapter.parse_feed(xml, reference_time=REFERENCE)
    assert len(records) == 1
    product = records[0]
    assert product.description is None
    assert product.website is None
    assert product.category is None
    assert product.company is None
    assert product.freshness_status == "unknown"


def test_product_duplicate_url_is_deduplicated():
    xml = '''
    <rss version="2.0"><channel>
      <item><title>Duplicate Product</title><link>https://example.com/products/dup</link><company>Acme</company><pubDate>Sat, 10 Jan 2026 10:00:00 GMT</pubDate></item>
      <item><title>Duplicate Product Again</title><link>https://example.com/products/dup</link><company>Acme</company><pubDate>Sat, 10 Jan 2026 10:00:00 GMT</pubDate></item>
    </channel></rss>
    '''
    adapter = ProductAdapter()
    result = adapter.crawl_feed(xml, reference_time=REFERENCE, max_age_hours=24)
    assert len(result.fresh_records) == 1


def test_product_date_states_are_distinguished():
    xml = '''
    <rss version="2.0"><channel>
      <item><title>Fresh Product</title><link>https://example.com/products/fresh</link><company>FreshCo</company><pubDate>Sat, 10 Jan 2026 11:00:00 GMT</pubDate></item>
      <item><title>Stale Product</title><link>https://example.com/products/stale</link><company>OldCo</company><pubDate>Thu, 08 Jan 2026 12:00:00 GMT</pubDate></item>
      <item><title>Future Product</title><link>https://example.com/products/future</link><company>FutureCo</company><pubDate>Sat, 10 Jan 2026 13:00:00 GMT</pubDate></item>
      <item><title>No Date Product</title><link>https://example.com/products/missing</link><company>MissingCo</company></item>
    </channel></rss>
    '''
    adapter = ProductAdapter()
    result = adapter.crawl_feed(xml, reference_time=REFERENCE, max_age_hours=24)
    assert len(result.fresh_records) == 1
    assert len(result.stale_records) == 1
    assert len(result.future_records) == 1
    assert len(result.unknown_records) == 1


@pytest.mark.asyncio
async def test_product_fetch_failure_is_captured():
    adapter = ProductAdapter(
        crawler=FakeCrawler(CrawlResult(requested_url="https://example.com/products/feed", success=False, error="boom", error_type="http_error"))
    )
    result = await adapter.crawl_products("https://example.com/products/feed", reference_time=REFERENCE)
    assert result.fetch_errors
    assert result.fresh_records == []


def test_product_malformed_feed_returns_empty_list():
    adapter = ProductAdapter()
    assert adapter.parse_feed("<rss><broken>", reference_time=REFERENCE) == []


def test_product_invalid_entries_do_not_fabricate_data():
    xml = '<rss><channel><item><description>missing name</description><link>https://example.com/products/no-title</link></item></channel></rss>'
    adapter = ProductAdapter()
    records = adapter.parse_feed(xml, reference_time=REFERENCE)
    assert records == []
