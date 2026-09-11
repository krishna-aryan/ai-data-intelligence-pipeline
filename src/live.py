from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from src.crawlers.http_client import AsyncHTTPCrawler
from src.crawlers.jobs import JobAdapter
from src.crawlers.news import NewsAdapter
from src.crawlers.products import ProductAdapter
from src.crawlers.research_papers import ResearchPaperAdapter
from src.crawlers.startups import StartupAdapter
from src.job_queue import AsyncJobQueueExecutor, JobExecutionError, PipelineJob
from src.llm import FallbackOrchestrator, build_default_providers
from src.pipeline import PipelineBatchResult, PipelineOrchestrator
from src.source_config import SourceConfiguration, SourceConfigurationError, load_source_configuration
from src.storage.repository import SQLiteRecordRepository


class LiveExecutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class LiveSourceResult:
    entity_type: str
    source_url: str
    status: str
    record_count: int = 0
    error: str | None = None


@dataclass(frozen=True)
class LiveRunResult:
    source_results: tuple[LiveSourceResult, ...]
    fetched_records: int
    skipped_sources: tuple[str, ...]
    pipeline_result: PipelineBatchResult | None
    extraction_available: bool
    messages: tuple[str, ...] = field(default_factory=tuple)


async def _fetch_source(
    entity_type: str,
    source_url: str,
    crawler: AsyncHTTPCrawler,
    *,
    reference_time: datetime | None = None,
) -> list[Any]:
    if entity_type == "startups":
        result = await StartupAdapter(crawler).crawl_startups(source_url, reference_time=reference_time)
        if result.fetch_errors or result.feed_errors:
            raise JobExecutionError(
                "; ".join(result.fetch_errors or result.feed_errors),
                category="source_fetch",
                details={"entity_type": entity_type, "source_url": source_url},
            )
        return result.fresh_records
    if entity_type == "products":
        result = await ProductAdapter(crawler).crawl_products(source_url, reference_time=reference_time)
        if result.fetch_errors or result.feed_errors:
            raise JobExecutionError(
                "; ".join(result.fetch_errors or result.feed_errors),
                category="source_fetch",
                details={"entity_type": entity_type, "source_url": source_url},
            )
        return result.fresh_records
    if entity_type == "jobs":
        result = await JobAdapter(crawler).crawl_jobs(source_url, reference_time=reference_time)
        if result.fetch_errors or result.feed_errors:
            raise JobExecutionError(
                "; ".join(result.fetch_errors or result.feed_errors),
                category="source_fetch",
                details={"entity_type": entity_type, "source_url": source_url},
            )
        return result.fresh_jobs
    if entity_type == "news":
        result = await NewsAdapter(crawler).crawl_news(source_url, reference_time=reference_time)
        if result.fetch_errors or result.feed_errors:
            raise JobExecutionError(
                "; ".join(result.fetch_errors or result.feed_errors),
                category="source_fetch",
                details={"entity_type": entity_type, "source_url": source_url},
            )
        return result.fresh_records
    if entity_type == "research_papers":
        return await ResearchPaperAdapter(crawler).fetch_and_parse(source_url)
    raise LiveExecutionError(f"Unsupported source entity type: {entity_type}")


def _record_request(entity_type: str, configured_url: str, record: Any) -> dict[str, str]:
    source_url = getattr(record, "source_url", None)
    if not source_url and getattr(record, "source", None) is not None:
        source_url = getattr(record.source, "url", None)
    content = getattr(record, "content", None)
    if not source_url and content is not None:
        source_url = getattr(content, "paper_url", None)
    return {
        "source_url": str(source_url or configured_url),
        "raw_text": record.model_dump_json(),
        "source_name": entity_type,
    }


async def run_live(
    *,
    configuration: SourceConfiguration | None = None,
    crawler: AsyncHTTPCrawler | Any | None = None,
    repository: SQLiteRecordRepository | None = None,
    provider: Any | None = None,
    source_handler: Callable[[str, str, Any], Awaitable[list[Any]]] = _fetch_source,
    reference_time: datetime | None = None,
) -> LiveRunResult:
    configuration = configuration or load_source_configuration()
    configured_sources = configuration.configured()
    if not configured_sources:
        missing = ", ".join(configuration.missing())
        raise SourceConfigurationError(
            f"No live source URLs configured. Set at least one of: {missing}."
        )

    crawler = crawler or AsyncHTTPCrawler()
    reference_time = reference_time or datetime.now(timezone.utc)
    source_jobs = [
        PipelineJob.create(source_url=url, entity_type=entity_type, payload=(entity_type, url))
        for entity_type, url in configured_sources
    ]

    async def ingest(job: PipelineJob[tuple[str, str]]) -> list[Any]:
        entity_type, source_url = job.payload
        if source_handler is _fetch_source:
            return await _fetch_source(entity_type, source_url, crawler, reference_time=reference_time)
        return await source_handler(entity_type, source_url, crawler)

    source_execution = await AsyncJobQueueExecutor[tuple[str, str], list[Any]](
        min(5, len(source_jobs))
    ).run(source_jobs, ingest)
    source_results: list[LiveSourceResult] = []
    requests: list[dict[str, str]] = []
    for item in source_execution.results:
        if item.status == "succeeded" and item.value is not None:
            entity_type, source_url = item.job.payload
            source_results.append(LiveSourceResult(entity_type, source_url, "succeeded", len(item.value)))
            requests.extend(_record_request(entity_type, source_url, record) for record in item.value)
        else:
            source_results.append(LiveSourceResult(
                item.job.entity_type,
                item.job.source_url,
                "failed",
                error=item.error_message or "Source ingestion failed.",
            ))

    skipped_sources = tuple(name for name, _ in ((
        ("startups", configuration.startups),
        ("products", configuration.products),
        ("research_papers", configuration.research_papers),
        ("jobs", configuration.jobs),
        ("news", configuration.news),
    )) if not _)
    if not requests:
        return LiveRunResult(tuple(source_results), 0, skipped_sources, None, False, ("No fresh records were produced by configured public sources.",))

    if provider is None:
        providers = build_default_providers()
        if not providers:
            return LiveRunResult(
                tuple(source_results),
                len(requests),
                skipped_sources,
                None,
                False,
                ("LLM extraction is unavailable: no configured Gemini, Groq, or Cerebras credentials.",),
            )
        provider = FallbackOrchestrator(providers)

    repository = repository or SQLiteRecordRepository()
    pipeline_result = await PipelineOrchestrator(repository, llm_provider=provider).process_batch(requests)
    return LiveRunResult(tuple(source_results), len(requests), skipped_sources, pipeline_result, True)


__all__ = ["LiveExecutionError", "LiveRunResult", "LiveSourceResult", "run_live"]