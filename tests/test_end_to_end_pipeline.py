import json
from datetime import datetime, timezone

import pytest

from src.crawlers.models import CrawlResult
from src.crawlers.news import NewsAdapter
from src.crawlers.jobs import JobAdapter
from src.crawlers.startups import StartupAdapter
from src.integrations.google_sheets import GoogleSheetsExporter
from src.models.schemas import ProductRecord, ResearchPaperRecord
from src.pipeline import PipelineOrchestrator
from src.storage.repository import SQLiteRecordRepository


class FakeHTTPClient:
    def __init__(self, payloads):
        self.payloads = payloads

    async def fetch(self, url):
        payload = self.payloads.get(url)
        if payload is None:
            return CrawlResult(requested_url=url, success=False, error="offline failure")
        return CrawlResult(requested_url=url, status=200, success=True, text=payload)


class FakeProvider:
    def __init__(self, payloads):
        self.payloads = payloads

    async def generate(self, prompt):
        for url, payload in self.payloads.items():
            if url in prompt:
                if payload == "FAIL":
                    raise RuntimeError("provider failure without credentials")
                return json.dumps(payload)
        raise RuntimeError("missing offline payload")


class FakeSheetsClient:
    def __init__(self):
        self.values = {}

    def ensure_worksheet(self, spreadsheet_id, worksheet_name):
        self.values.setdefault(worksheet_name, [])

    def replace_values(self, spreadsheet_id, worksheet_name, values):
        self.values[worksheet_name] = [list(row) for row in values]


def _payload(record_type, url, content):
    return {"records": [{"recordType": record_type, "schemaVersion": "1.0", "source": {"name": "Offline", "url": url}, "content": content, "collectedAt": "2026-09-11T12:00:00Z"}]}


@pytest.mark.asyncio
async def test_complete_offline_pipeline_is_deterministic_and_idempotent(tmp_path):
    reference = datetime(2026, 9, 11, 12, tzinfo=timezone.utc)
    startup_url = "https://offline.test/startup"
    product_url = "https://offline.test/product"
    paper_url = "https://offline.test/paper"
    job_url = "https://offline.test/job"
    news_url = "https://offline.test/news"
    feed_payloads = {
        "https://offline.test/startups-feed": '<rss><channel><item><title>Open AI</title><link>https://offline.test/startup</link><pubDate>Fri, 11 Sep 2026 11:00:00 GMT</pubDate></item></channel></rss>',
        "https://offline.test/jobs-feed": '<rss><channel><item><title>Engineer</title><link>https://offline.test/job</link><source>OpenAI</source><pubDate>Fri, 11 Sep 2026 11:00:00 GMT</pubDate></item></channel></rss>',
        "https://offline.test/news-feed": '<rss><channel><item><title>Launch</title><link>https://offline.test/news</link><pubDate>Fri, 11 Sep 2026 11:00:00 GMT</pubDate></item></channel></rss>',
    }
    startups = await StartupAdapter(FakeHTTPClient(feed_payloads)).crawl_startups("https://offline.test/startups-feed", reference_time=reference)
    jobs = await JobAdapter(FakeHTTPClient(feed_payloads)).crawl_jobs("https://offline.test/jobs-feed", reference_time=reference)
    news = await NewsAdapter(FakeHTTPClient(feed_payloads)).crawl_news("https://offline.test/news-feed", reference_time=reference)
    assert startups.fresh_records[0].freshness_status == "fresh"
    assert jobs.fresh_jobs[0].freshness_status == "fresh"
    assert news.fresh_records[0].freshness_status == "fresh"

    llm_payloads = {
        startup_url: _payload("STARTUP", startup_url, {"entityName": "Open AI", "employeeCount": 10}),
        product_url: _payload("PRODUCT", product_url, {"startupName": "Unknown Company", "pricingModel": "usage_based"}),
        paper_url: _payload("RESEARCH_PAPER", paper_url, {"title": "Paper", "authors": ["Author"], "paper_url": "https://papers.test/paper"}),
        job_url: _payload("JOB", job_url, {"company": "OpenAI", "date": "2026-09-11", "role_family": "Engineer"}),
        news_url: _payload("NEWS", news_url, {"title": "Launch", "summary": "Summary", "published_at": "2026-09-11T11:00:00Z"}),
        "https://offline.test/failure": "FAIL",
    }
    repo = SQLiteRecordRepository(tmp_path / "e2e.sqlite3")
    records = [
        {"source_url": startup_url, "raw_text": "Open AI"},
        {"source_url": product_url, "raw_text": "Unknown Company"},
        {"source_url": paper_url, "raw_text": "Paper"},
        {"source_url": job_url, "raw_text": "Engineer"},
        {"source_url": news_url, "raw_text": "Launch"},
        {"source_url": "https://offline.test/failure", "raw_text": "bad"},
    ]
    orchestrator = PipelineOrchestrator(repo, llm_provider=FakeProvider(llm_payloads), batch_concurrency=2)
    result = await orchestrator.process_batch(records)

    assert result.queued == 6
    assert result.succeeded == 5
    assert result.failed == 1
    assert result.persisted == 5
    assert result.extracted == 5
    assert result.resolved == 1
    assert result.unresolved == 1
    for url in (startup_url, product_url, paper_url, job_url, news_url):
        assert repo.get_by_source_url(url) is not None
    assert repo.get_by_source_url(paper_url).content.github_url is None
    assert repo.get_by_source_url(startup_url).content.entityName == "Open AI"
    assert repo.get_by_source_url(product_url).content.entityResolution.canonical_name is None

    client = FakeSheetsClient()
    exporter = GoogleSheetsExporter(repo, client, spreadsheet_id="offline-sheet")
    first = exporter.export()
    snapshot = {name: list(rows) for name, rows in client.values.items()}
    second = exporter.export()
    assert first == second
    assert client.values == snapshot
    assert len(client.values) == 6
    assert len(client.values["Startups"]) == 2
    assert len(client.values["Products"]) == 2