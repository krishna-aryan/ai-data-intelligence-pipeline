from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.freshness import evaluate_freshness, parse_publication_date
from src.models.news import NewsArticle

from .http_client import AsyncHTTPCrawler


class NewsFetchEntry(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str | None = None
    source_url: str | None = None
    published_date: datetime | None = None
    raw_published_date: str | None = None
    source: str | None = None
    description: str | None = None
    author: str | None = None
    freshness_status: str | None = None
    freshness_reason: str | None = None


class NewsIngestionResult(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    source_url: str | None = None
    fresh_records: list[NewsArticle] = Field(default_factory=list)
    stale_records: list[NewsArticle] = Field(default_factory=list)
    unknown_records: list[NewsArticle] = Field(default_factory=list)
    future_records: list[NewsArticle] = Field(default_factory=list)
    fetch_errors: list[str] = Field(default_factory=list)
    feed_errors: list[str] = Field(default_factory=list)
    excluded_records: list[NewsArticle] = Field(default_factory=list)

    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return super().model_dump(*args, **kwargs)


class NewsAdapter:
    """Parse public RSS/Atom feeds into deterministic news records with freshness filtering."""

    source_name = "Public RSS feed"
    source_url = "https://example.com/feed"

    def __init__(self, crawler: Any | None = None) -> None:
        self.crawler = crawler or AsyncHTTPCrawler(timeout=15.0, max_concurrency=5)

    def parse_feed(self, feed_xml: str, *, reference_time: datetime | None = None, max_age_hours: float = 24) -> list[NewsArticle]:
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

        records: list[NewsArticle] = []
        seen_urls: set[str] = set()

        for item in items:
            parsed = self._parse_item(item, reference_time=reference_time, max_age_hours=max_age_hours)
            if parsed is None:
                continue
            key = self._dedupe_key(parsed.source_url) or self._dedupe_key(parsed.title)
            if not key or key in seen_urls:
                continue
            seen_urls.add(key)
            records.append(parsed)

        return records

    def crawl_feed(self, feed_xml: str, *, reference_time: datetime | None = None, max_age_hours: float = 24) -> NewsIngestionResult:
        if reference_time is None:
            reference_time = datetime.now(timezone.utc)

        fresh_records: list[NewsArticle] = []
        stale_records: list[NewsArticle] = []
        unknown_records: list[NewsArticle] = []
        future_records: list[NewsArticle] = []
        excluded_records: list[NewsArticle] = []

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

        return NewsIngestionResult(
            source_url=None,
            fresh_records=fresh_records,
            stale_records=stale_records,
            unknown_records=unknown_records,
            future_records=future_records,
            excluded_records=excluded_records,
        )

    async def crawl_news(self, url: str, *, reference_time: datetime | None = None, max_age_hours: float = 24) -> NewsIngestionResult:
        if reference_time is None:
            reference_time = datetime.now(timezone.utc)

        response = await self.crawler.fetch(url)
        if not response.success:
            return NewsIngestionResult(
                source_url=url,
                fetch_errors=[response.error or "Fetch failed"],
            )

        try:
            feed = response.text
            parsed = self.parse_feed(feed, reference_time=reference_time, max_age_hours=max_age_hours)
        except Exception as exc:
            return NewsIngestionResult(
                source_url=url,
                feed_errors=[str(exc)],
            )

        fresh_records = [record for record in parsed if record.freshness_status == "fresh"]
        stale_records = [record for record in parsed if record.freshness_status == "stale"]
        unknown_records = [record for record in parsed if record.freshness_status == "unknown"]
        future_records = [record for record in parsed if record.freshness_status == "future"]

        return NewsIngestionResult(
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
        return re.sub(r"[?#].*$", "", value.strip().lower())

    def _parse_item(self, item: Any, *, reference_time: datetime, max_age_hours: float) -> NewsArticle | None:
        title = self._extract_value(item, "title")
        if not title:
            return None

        url = self._extract_value(item, "link")
        if not url:
            url = self._extract_value(item, "guid")
        if not url:
            url = self._extract_value(item, "url")

        published_value = self._extract_value(item, "pubDate")
        if not published_value:
            published_value = self._extract_value(item, "pubdate")
        if not published_value:
            published_value = self._extract_value(item, "published")
        if not published_value:
            published_value = self._extract_value(item, "updated")

        article = NewsArticle(
            title=title,
            source_url=url,
            raw_published_date=published_value,
            source=self.source_name,
            description=self._extract_value(item, "description") or None,
            author=self._extract_value(item, "author") or None,
            published_date=None,
        )

        date_result = parse_publication_date(published_value, reference_time)
        if date_result.status in {"missing", "unparseable"}:
            article.freshness_status = "unknown"
            article.freshness_reason = date_result.reason
            article.published_date = None
            return article

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


__all__ = ["NewsAdapter", "NewsFetchEntry", "NewsIngestionResult"]
