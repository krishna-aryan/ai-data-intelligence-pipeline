from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.freshness import evaluate_freshness, parse_publication_date
from src.models.products import ProductArticle

from .http_client import AsyncHTTPCrawler


class ProductIngestionResult(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    source_url: str | None = None
    fresh_records: list[ProductArticle] = Field(default_factory=list)
    stale_records: list[ProductArticle] = Field(default_factory=list)
    unknown_records: list[ProductArticle] = Field(default_factory=list)
    future_records: list[ProductArticle] = Field(default_factory=list)
    fetch_errors: list[str] = Field(default_factory=list)
    feed_errors: list[str] = Field(default_factory=list)
    excluded_records: list[ProductArticle] = Field(default_factory=list)

    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return super().model_dump(*args, **kwargs)


class ProductAdapter:
    """Parse a public RSS/Atom product feed into deterministic product records."""

    source_name = "Public product RSS feed"
    source_url = "https://example.com/products"

    def __init__(self, crawler: Any | None = None) -> None:
        self.crawler = crawler or AsyncHTTPCrawler(timeout=15.0, max_concurrency=5)

    def parse_feed(self, feed_xml: str, *, reference_time: datetime | None = None, max_age_hours: float = 24) -> list[ProductArticle]:
        if reference_time is None:
            reference_time = datetime.now(timezone.utc)

        if not feed_xml or not feed_xml.strip():
            return []

        try:
            root = ET.fromstring(feed_xml)
        except ET.ParseError:
            return []

        items: list[Any] = []
        for tag_name in ("item", "entry"):
            items.extend(root.iter(tag_name))

        records: list[ProductArticle] = []
        seen_urls: set[str] = set()

        for item in items:
            parsed = self._parse_item(item, reference_time=reference_time, max_age_hours=max_age_hours)
            if parsed is None:
                continue
            key = self._dedupe_key(parsed.source_url) or self._dedupe_key(parsed.name)
            if not key or key in seen_urls:
                continue
            seen_urls.add(key)
            records.append(parsed)

        return records

    def crawl_feed(self, feed_xml: str, *, reference_time: datetime | None = None, max_age_hours: float = 24) -> ProductIngestionResult:
        if reference_time is None:
            reference_time = datetime.now(timezone.utc)

        fresh_records: list[ProductArticle] = []
        stale_records: list[ProductArticle] = []
        unknown_records: list[ProductArticle] = []
        future_records: list[ProductArticle] = []
        excluded_records: list[ProductArticle] = []

        records = self.parse_feed(feed_xml, reference_time=reference_time, max_age_hours=max_age_hours)
        for record in records:
            if record.freshness_status == "fresh":
                fresh_records.append(record)
            elif record.freshness_status == "stale":
                stale_records.append(record)
            elif record.freshness_status == "unknown":
                unknown_records.append(record)
            elif record.freshness_status == "future":
                future_records.append(record)
            else:
                unknown_records.append(record)

            if record.freshness_status in {"stale", "unknown", "future"}:
                excluded_records.append(record)

        return ProductIngestionResult(
            source_url=None,
            fresh_records=fresh_records,
            stale_records=stale_records,
            unknown_records=unknown_records,
            future_records=future_records,
            excluded_records=excluded_records,
        )

    async def crawl_products(self, url: str, *, reference_time: datetime | None = None, max_age_hours: float = 24) -> ProductIngestionResult:
        if reference_time is None:
            reference_time = datetime.now(timezone.utc)

        response = await self.crawler.fetch(url)
        if not response.success:
            return ProductIngestionResult(
                source_url=url,
                fetch_errors=[response.error or "Fetch failed"],
            )

        try:
            feed = response.text
            parsed = self.parse_feed(feed, reference_time=reference_time, max_age_hours=max_age_hours)
        except Exception as exc:
            return ProductIngestionResult(
                source_url=url,
                feed_errors=[str(exc)],
            )

        fresh_records = [record for record in parsed if record.freshness_status == "fresh"]
        stale_records = [record for record in parsed if record.freshness_status == "stale"]
        unknown_records = [record for record in parsed if record.freshness_status == "unknown"]
        future_records = [record for record in parsed if record.freshness_status == "future"]

        return ProductIngestionResult(
            source_url=url,
            fresh_records=fresh_records,
            stale_records=stale_records,
            unknown_records=unknown_records,
            future_records=future_records,
            excluded_records=[*stale_records, *unknown_records, *future_records],
        )

    def _dedupe_key(self, value: str | None) -> str:
        if not value:
            return ""
        normalized = re.sub(r"[?#].*$", "", value.strip().lower())
        normalized = normalized.rstrip("/")
        return normalized

    def _parse_item(self, item: Any, *, reference_time: datetime, max_age_hours: float) -> ProductArticle | None:
        name = self._extract_value(item, "title") or self._extract_value(item, "name")
        if not name:
            return None

        url = self._extract_value(item, "link")
        if not url:
            url = self._extract_value(item, "guid")
        if not url:
            url = self._extract_value(item, "url")
        if not url:
            return None

        published_value = self._extract_value(item, "pubDate")
        if not published_value:
            published_value = self._extract_value(item, "pubdate")
        if not published_value:
            published_value = self._extract_value(item, "published")
        if not published_value:
            published_value = self._extract_value(item, "updated")

        article = ProductArticle(
            name=name,
            company=self._extract_value(item, "company") or self._extract_value(item, "source") or None,
            source_url=url,
            raw_published_date=published_value,
            source=self._extract_value(item, "source") or self.source_name,
            description=self._extract_value(item, "description") or None,
            website=self._extract_value(item, "website") or self._extract_value(item, "url") or None,
            category=self._extract_value(item, "category") or None,
            published_date=None,
        )

        date_result = parse_publication_date(published_value, reference_time)
        if date_result.status in {"missing", "unparseable"}:
            article.freshness_status = "unknown"
            article.freshness_reason = date_result.reason
            article.published_date = None
        else:
            article.published_date = date_result.normalized_datetime
            freshness = evaluate_freshness(article.published_date, reference_time, max_age_hours=max_age_hours)
            article.freshness_status = freshness.status
            article.freshness_reason = freshness.reason

        return article

    def _extract_value(self, item: Any, field: str) -> str | None:
        if item is None:
            return None

        tag_name = field.lower()
        for candidate in (field, tag_name):
            element = item.find(candidate)
            if element is not None and element.text:
                return element.text.strip() or None

        for candidate in (field, tag_name):
            for child in list(item):
                if child.tag.lower() == candidate.lower() and child.text:
                    return child.text.strip() or None

        for key in (field, tag_name):
            if item.tag is not None and item.tag.lower() == key.lower() and item.text:
                return item.text.strip() or None

        if hasattr(item, "attrib"):
            for key in (field, tag_name):
                value = item.attrib.get(key)
                if value:
                    return value.strip()

        return None


__all__ = ["ProductAdapter", "ProductIngestionResult"]
