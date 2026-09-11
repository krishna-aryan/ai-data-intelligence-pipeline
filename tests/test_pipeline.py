import json
from pathlib import Path

import pytest

from src.pipeline import PipelineBatchResult, PipelineOrchestrator
from src.storage.repository import SQLiteRecordRepository


class FakeLLMProvider:
    def __init__(self, payload):
        self.payload = payload

    async def generate(self, prompt: str) -> str:
        return json.dumps(self.payload)


@pytest.mark.asyncio
async def test_pipeline_orchestrator_persists_valid_records(tmp_path: Path):
    db_path = tmp_path / "pipeline.sqlite3"
    repo = SQLiteRecordRepository(db_path)
    provider = FakeLLMProvider(
        {
            "records": [
                {
                    "recordType": "STARTUP",
                    "schemaVersion": "1.0",
                    "source": {"name": "Example", "url": "https://example.com/startup"},
                    "content": {"entityName": "GraphOne", "employeeCount": 15},
                    "collectedAt": "2026-09-11T12:00:00Z",
                }
            ]
        }
    )

    orchestrator = PipelineOrchestrator(repo, llm_provider=provider)
    result = await orchestrator.process_batch(
        [{"source_url": "https://example.com/startup", "raw_text": "GraphOne has 15 employees.", "source_name": "Example"}]
    )

    assert isinstance(result, PipelineBatchResult)
    assert result.total == 1
    assert result.processed == 1
    assert result.stored == 1
    assert result.failed == 0
    assert len(repo.get_by_type("STARTUP")) == 1


@pytest.mark.asyncio
async def test_pipeline_orchestrator_isolates_failures_per_record(tmp_path: Path):
    db_path = tmp_path / "pipeline.sqlite3"
    repo = SQLiteRecordRepository(db_path)

    class BadProvider:
        async def generate(self, prompt: str) -> str:
            return '{"records": [{"recordType": "NEWS", "schemaVersion": "1.0", "source": {"name": "Example", "url": "https://example.com/news"}, "content": {"summary": "missing required title"}, "collectedAt": "2026-09-11T12:00:00Z"}]}'

    orchestrator = PipelineOrchestrator(repo, llm_provider=BadProvider())
    result = await orchestrator.process_batch(
        [
            {"source_url": "https://example.com/good", "raw_text": "GraphOne launch", "source_name": "Example"},
            {"source_url": "https://example.com/bad", "raw_text": "Bad news", "source_name": "Example"},
        ],
        provider_response_overrides={
            "https://example.com/good": json.dumps({
                "records": [{
                    "recordType": "PRODUCT",
                    "schemaVersion": "1.0",
                    "source": {"name": "Example", "url": "https://example.com/good"},
                    "content": {"startupName": "GraphOne", "pricingModel": "usage_based"},
                    "collectedAt": "2026-09-11T12:00:00Z",
                }]
            }),
        },
    )

    assert result.total == 2
    assert result.processed == 1
    assert result.failed == 1
    assert result.stored == 1
    assert len(repo.get_by_type("PRODUCT")) == 1
    assert len(result.failures) == 1
