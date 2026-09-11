import json
from pathlib import Path

import pytest

from src.pipeline import PipelineOrchestrator
from src.storage.repository import SQLiteRecordRepository


def startup_payload(url: str, name: str) -> dict:
    return {
        "records": [{
            "recordType": "STARTUP",
            "schemaVersion": "1.0",
            "source": {"name": "Feed", "url": url},
            "content": {"entityName": name},
            "collectedAt": "2026-09-11T12:00:00Z",
        }]
    }


def product_payload(url: str, name: str) -> dict:
    return {
        "records": [{
            "recordType": "PRODUCT",
            "schemaVersion": "1.0",
            "source": {"name": "Feed", "url": url},
            "content": {"startupName": name, "pricingModel": "usage_based"},
            "collectedAt": "2026-09-11T12:00:00Z",
        }]
    }


class StaticProvider:
    def __init__(self, payloads: dict[str, dict]) -> None:
        self.payloads = payloads

    async def generate(self, prompt: str) -> str:
        for url, payload in self.payloads.items():
            if url in prompt:
                return json.dumps(payload)
        raise RuntimeError("missing payload")


@pytest.mark.asyncio
async def test_pipeline_persists_exact_canonical_startup_resolution(tmp_path: Path):
    url = "https://example.com/canonical"
    repo = SQLiteRecordRepository(tmp_path / "pipeline.sqlite3")
    await PipelineOrchestrator(
        repo,
        llm_provider=StaticProvider({url: startup_payload(url, "OpenAI")}),
        batch_concurrency=1,
    ).process_batch([{"source_url": url, "raw_text": "OpenAI"}])

    saved = repo.get_by_source_url(url)
    assert saved.content.entityResolution.canonical_name == "OpenAI"
    assert saved.content.entityResolution.match_type == "exact_canonical"


@pytest.mark.asyncio
async def test_pipeline_resolves_product_startup_name(tmp_path: Path):
    url = "https://example.com/product"
    repo = SQLiteRecordRepository(tmp_path / "pipeline.sqlite3")
    await PipelineOrchestrator(
        repo,
        llm_provider=StaticProvider({url: product_payload(url, "Anthropic AI")}),
        batch_concurrency=1,
    ).process_batch([{"source_url": url, "raw_text": "Anthropic AI product"}])

    saved = repo.get_by_source_url(url)
    assert saved.content.startupName == "Anthropic AI"
    assert saved.content.entityResolution.canonical_name == "Anthropic"
    assert saved.content.entityResolution.match_type == "exact_alias"


@pytest.mark.asyncio
async def test_pipeline_persists_exact_alias_resolution_and_mapping_log(tmp_path: Path):
    url = "https://example.com/startup"
    repo = SQLiteRecordRepository(tmp_path / "pipeline.sqlite3")
    result = await PipelineOrchestrator(
        repo,
        llm_provider=StaticProvider({url: startup_payload(url, "Open AI")}),
        batch_concurrency=1,
    ).process_batch([{"source_url": url, "raw_text": "Open AI"}])

    saved = repo.get_by_source_url(url)
    logs = repo.get_mapping_logs(source_url=url)
    assert result.succeeded == 1
    assert saved is not None
    assert saved.content.entityName == "Open AI"
    assert saved.content.entityResolution.canonical_name == "OpenAI"
    assert saved.content.entityResolution.match_type == "exact_alias"
    assert str(saved.source.url) == url
    assert len(logs) == 1
    assert logs[0].original_name == "Open AI"
    assert logs[0].canonical_name == "OpenAI"


@pytest.mark.asyncio
async def test_pipeline_persists_unresolved_entity_and_is_idempotent(tmp_path: Path):
    url = "https://example.com/unknown"
    repo = SQLiteRecordRepository(tmp_path / "pipeline.sqlite3")
    orchestrator = PipelineOrchestrator(
        repo,
        llm_provider=StaticProvider({url: startup_payload(url, "Unknown Company")}),
        batch_concurrency=1,
    )
    item = {"source_url": url, "raw_text": "Unknown Company"}
    await orchestrator.process_batch([item])
    await orchestrator.process_batch([item])

    saved = repo.get_by_source_url(url)
    assert saved.content.entityResolution.canonical_name is None
    assert saved.content.entityResolution.match_type == "unresolved"
    assert repo.count_mapping_logs() == 1
    assert repo.count_by_type("STARTUP") == 1


@pytest.mark.asyncio
async def test_entity_resolution_failure_isolated_from_other_records(tmp_path: Path):
    first = "https://example.com/first"
    second = "https://example.com/second"
    repo = SQLiteRecordRepository(tmp_path / "pipeline.sqlite3")
    resolver = __import__("src.entity_resolution", fromlist=["EntityResolver"]).EntityResolver()
    original = resolver.resolve_startup

    def fail_for_one(name: str, source_url: str | None = None):
        if source_url == first:
            raise RuntimeError("resolver failure")
        return original(name, source_url=source_url)

    resolver.resolve_startup = fail_for_one
    provider = StaticProvider({first: startup_payload(first, "OpenAI"), second: startup_payload(second, "Anthropic")})
    result = await PipelineOrchestrator(repo, llm_provider=provider, entity_resolver=resolver, batch_concurrency=2).process_batch([
        {"source_url": first, "raw_text": "OpenAI"},
        {"source_url": second, "raw_text": "Anthropic"},
    ])

    assert result.succeeded == 1
    assert result.failed == 1
    assert repo.get_by_source_url(second) is not None