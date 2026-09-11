from __future__ import annotations

import asyncio
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.crawlers.jobs import JobAdapter
from src.crawlers.models import CrawlResult
from src.crawlers.news import NewsAdapter
from src.crawlers.products import ProductAdapter
from src.crawlers.research_papers import ResearchPaperAdapter
from src.crawlers.startups import StartupAdapter
from src.integrations.google_sheets import GoogleSheetsExporter
from src.pipeline import PipelineBatchResult, PipelineOrchestrator
from src.storage.repository import SQLiteRecordRepository


DEMO_REFERENCE_TIME = datetime(2026, 9, 11, 12, tzinfo=timezone.utc)


class DemoHTTPClient:
    def __init__(self, responses: dict[str, str]) -> None:
        self.responses = responses

    async def fetch(self, url: str, *, headers: dict[str, str] | None = None) -> CrawlResult:
        text = self.responses.get(url)
        if text is None:
            return CrawlResult(requested_url=url, success=False, error="DEMO fixture missing")
        return CrawlResult(requested_url=url, status=200, success=True, text=text)


class DemoLLMProvider:
    provider_name = "demo-fake-provider"

    def __init__(self, responses: dict[str, dict[str, Any] | str]) -> None:
        self.responses = responses

    async def generate(self, prompt: str) -> str:
        for source_url, response in self.responses.items():
            if source_url in prompt:
                if response == "FAIL":
                    raise RuntimeError("DEMO fixture provider failure")
                return json.dumps(response)
        raise RuntimeError("DEMO fixture has no response for this source URL")


class DemoSheetsClient:
    def __init__(self) -> None:
        self.values: dict[str, list[list[Any]]] = {}

    def ensure_worksheet(self, spreadsheet_id: str, worksheet_name: str) -> None:
        self.values.setdefault(worksheet_name, [])

    def replace_values(self, spreadsheet_id: str, worksheet_name: str, values: list[list[Any]]) -> None:
        self.values[worksheet_name] = [list(row) for row in values]


def _payload(record_type: str, source_url: str, content: dict[str, Any]) -> dict[str, Any]:
    return {
        "records": [{
            "recordType": record_type,
            "schemaVersion": "1.0",
            "source": {"name": "DEMO / TEST FIXTURE", "url": source_url},
            "content": content,
            "collectedAt": "2026-09-11T12:00:00Z",
        }]
    }


async def run_offline_demo() -> tuple[PipelineBatchResult, tuple[str, ...], Path]:
    """Run the complete pipeline with deterministic fixtures and temporary SQLite."""
    startup_url = "https://demo.invalid/startup"
    product_url = "https://demo.invalid/product"
    paper_url = "https://demo.invalid/paper"
    job_url = "https://demo.invalid/job"
    news_url = "https://demo.invalid/news"
    feed_responses = {
        "https://demo.invalid/startups-feed": (
            "<rss><channel><item><title>Open AI</title>"
            "<link>https://demo.invalid/startup</link>"
            "<pubDate>Fri, 11 Sep 2026 11:00:00 GMT</pubDate>"
            "</item></channel></rss>"
        ),
        "https://demo.invalid/products-feed": (
            "<rss><channel><item><title>Demo Product</title>"
            "<link>https://demo.invalid/product</link>"
            "<pubDate>Fri, 11 Sep 2026 11:00:00 GMT</pubDate>"
            "</item></channel></rss>"
        ),
        "https://demo.invalid/jobs-feed": (
            "<rss><channel><item><title>Demo Engineer</title>"
            "<link>https://demo.invalid/job</link><source>OpenAI</source>"
            "<pubDate>Fri, 11 Sep 2026 11:00:00 GMT</pubDate>"
            "</item></channel></rss>"
        ),
        "https://demo.invalid/news-feed": (
            "<rss><channel><item><title>Demo Launch</title>"
            "<link>https://demo.invalid/news</link>"
            "<pubDate>Fri, 11 Sep 2026 11:00:00 GMT</pubDate>"
            "</item></channel></rss>"
        ),
    }
    crawler = DemoHTTPClient(feed_responses)
    startup_result = await StartupAdapter(crawler).crawl_startups(
        "https://demo.invalid/startups-feed", reference_time=DEMO_REFERENCE_TIME
    )
    product_result = await ProductAdapter(crawler).crawl_products(
        "https://demo.invalid/products-feed", reference_time=DEMO_REFERENCE_TIME
    )
    job_result = await JobAdapter(crawler).crawl_jobs(
        "https://demo.invalid/jobs-feed", reference_time=DEMO_REFERENCE_TIME
    )
    news_result = await NewsAdapter(crawler).crawl_news(
        "https://demo.invalid/news-feed", reference_time=DEMO_REFERENCE_TIME
    )
    paper_result = ResearchPaperAdapter().parse_response({
        "data": [{
            "title": "DEMO Research Paper",
            "authors": [{"name": "DEMO Author"}],
            "url": "https://demo.invalid/paper",
        }]
    })
    if not all([
        startup_result.fresh_records,
        product_result.fresh_records,
        job_result.fresh_jobs,
        news_result.fresh_records,
        paper_result,
    ]):
        raise RuntimeError("DEMO fixture ingestion did not produce all five entity types")

    llm_responses = {
        startup_url: _payload("STARTUP", startup_url, {"entityName": "Open AI", "employeeCount": 10}),
        product_url: _payload("PRODUCT", product_url, {"startupName": "Unknown Demo Company", "pricingModel": "usage_based"}),
        paper_url: _payload("RESEARCH_PAPER", paper_url, {"title": "DEMO Research Paper", "authors": ["DEMO Author"], "paper_url": "https://demo.invalid/paper"}),
        job_url: _payload("JOB", job_url, {"company": "OpenAI", "date": "2026-09-11", "role_family": "Engineer"}),
        news_url: _payload("NEWS", news_url, {"title": "DEMO Launch", "summary": "DEMO summary", "published_at": "2026-09-11T11:00:00Z"}),
        "https://demo.invalid/failure": "FAIL",
    }
    records = [
        {"source_url": startup_url, "raw_text": "DEMO Open AI"},
        {"source_url": product_url, "raw_text": "DEMO Unknown Company"},
        {"source_url": paper_url, "raw_text": "DEMO paper"},
        {"source_url": job_url, "raw_text": "DEMO job"},
        {"source_url": news_url, "raw_text": "DEMO news"},
        {"source_url": "https://demo.invalid/failure", "raw_text": "DEMO intentional failure"},
    ]

    with tempfile.TemporaryDirectory(prefix="graphone-demo-") as temporary_directory:
        database_path = Path(temporary_directory) / "demo.sqlite3"
        repository = SQLiteRecordRepository(database_path)
        result = await PipelineOrchestrator(
            repository,
            llm_provider=DemoLLMProvider(llm_responses),
            batch_concurrency=2,
        ).process_batch(records)
        sheets_client = DemoSheetsClient()
        exporter = GoogleSheetsExporter(repository, sheets_client, spreadsheet_id="demo-spreadsheet")
        exporter.export()
        exported_tabs = tuple(sheets_client.values)
        repository.close()
        return result, exported_tabs, database_path


def run_demo_sync() -> tuple[PipelineBatchResult, tuple[str, ...], Path]:
    return asyncio.run(run_offline_demo())


__all__ = ["run_demo_sync", "run_offline_demo"]