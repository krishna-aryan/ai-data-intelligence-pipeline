import json

import pytest

from src.llm import LLMExtractor
from src.models.schemas import JobRecord, NewsRecord, ProductRecord, ResearchPaperRecord, StartupRecord


class FakeProvider:
    def __init__(self, response: str | None = None, *, error: Exception | None = None):
        self.response = response
        self.error = error

    async def generate(self, prompt: str) -> str:
        if self.error is not None:
            raise self.error
        if self.response is None:
            return ""
        return self.response


class FakeProviderWithPromptCapture(FakeProvider):
    def __init__(self, response: str | None = None, *, error: Exception | None = None):
        super().__init__(response, error=error)
        self.last_prompt = None

    async def generate(self, prompt: str) -> str:
        self.last_prompt = prompt
        return await super().generate(prompt)


@pytest.mark.asyncio
async def test_valid_structured_response():
    payload = {
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
    extractor = LLMExtractor(FakeProvider(json.dumps(payload)))

    result = await extractor.extract(source_url="https://example.com/startup", raw_text="GraphOne has 15 employees.")

    assert result.ok is True
    assert len(result.records) == 1
    assert isinstance(result.records[0], StartupRecord)
    assert result.records[0].content.entityName == "GraphOne"
    assert str(result.records[0].source.url) == "https://example.com/startup"


@pytest.mark.asyncio
async def test_valid_response_with_optional_missing_fields():
    payload = {
        "records": [
            {
                "recordType": "JOB",
                "schemaVersion": "1.0",
                "source": {"name": "JobsBoard", "url": "https://jobs.example.com/posting"},
                "content": {"company": "GraphOne", "date": "2026-09-11", "is_remote": True, "role_family": "machine_learning"},
                "collectedAt": "2026-09-11T12:00:00Z",
            }
        ]
    }
    extractor = LLMExtractor(FakeProvider(json.dumps(payload)))

    result = await extractor.extract(source_url="https://jobs.example.com/posting", raw_text="Job listing for GraphOne.")

    assert result.ok is True
    assert isinstance(result.records[0], JobRecord)
    assert result.records[0].content.role_family == "machine_learning"


@pytest.mark.asyncio
async def test_malformed_json_rejected():
    extractor = LLMExtractor(FakeProvider("{not valid json}"))

    result = await extractor.extract(source_url="https://example.com", raw_text="test")

    assert result.ok is False
    assert result.error_type == "invalid_json"


@pytest.mark.asyncio
async def test_schema_validation_failure_rejected():
    payload = {
        "records": [
            {
                "recordType": "NEWS",
                "schemaVersion": "1.0",
                "source": {"name": "Example", "url": "https://example.com/news"},
                "content": {"summary": "Summary only"},
                "collectedAt": "2026-09-11T12:00:00Z",
            }
        ]
    }
    extractor = LLMExtractor(FakeProvider(json.dumps(payload)))

    result = await extractor.extract(source_url="https://example.com/news", raw_text="A news story.")

    assert result.ok is False
    assert result.error_type == "schema_validation_failure"


@pytest.mark.asyncio
async def test_empty_response_rejected():
    extractor = LLMExtractor(FakeProvider(""))

    result = await extractor.extract(source_url="https://example.com", raw_text="text")

    assert result.ok is False
    assert result.error_type == "empty_response"


@pytest.mark.asyncio
async def test_provider_failure_is_structured():
    extractor = LLMExtractor(FakeProvider(error=RuntimeError("provider down")))

    result = await extractor.extract(source_url="https://example.com", raw_text="text")

    assert result.ok is False
    assert result.error_type == "provider_failure"


@pytest.mark.asyncio
async def test_source_url_preserved_and_not_replaced():
    payload = {
        "records": [
            {
                "recordType": "PRODUCT",
                "schemaVersion": "1.0",
                "source": {"name": "Example", "url": "https://invented.invalid"},
                "content": {"startupName": "GraphOne", "pricingModel": "usage_based"},
                "collectedAt": "2026-09-11T12:00:00Z",
            }
        ]
    }
    extractor = LLMExtractor(FakeProvider(json.dumps(payload)))

    result = await extractor.extract(source_url="https://real-source.example/product", raw_text="A product page.")

    assert result.ok is True
    assert str(result.records[0].source.url) == "https://real-source.example/product"


@pytest.mark.asyncio
async def test_extractor_refuses_to_invent_missing_values():
    payload = {
        "records": [
            {
                "recordType": "RESEARCH_PAPER",
                "schemaVersion": "1.0",
                "source": {"name": "Paper", "url": "https://example.com/paper"},
                "content": {
                    "title": "A paper",
                    "authors": ["Ada Lovelace"],
                    "paper_url": "https://example.com/paper/link",
                    "github_url": None,
                    "github_stars": None,
                    "published_date": None,
                },
                "collectedAt": "2026-09-11T12:00:00Z",
            }
        ]
    }
    extractor = LLMExtractor(FakeProvider(json.dumps(payload)))

    result = await extractor.extract(source_url="https://example.com/paper", raw_text="Paper summary only.")

    assert result.ok is True
    assert result.records[0].content.github_url is None
    assert result.records[0].content.github_stars is None
    assert result.records[0].content.published_date is None


@pytest.mark.asyncio
async def test_extractor_extracts_startup_product_paper_job_and_news():
    payload = {
        "records": [
            {
                "recordType": "STARTUP",
                "schemaVersion": "1.0",
                "source": {"name": "Source", "url": "https://example.com/startup"},
                "content": {"entityName": "GraphOne", "employeeCount": 30},
                "collectedAt": "2026-09-11T12:00:00Z",
            },
            {
                "recordType": "PRODUCT",
                "schemaVersion": "1.0",
                "source": {"name": "Source", "url": "https://example.com/product"},
                "content": {"startupName": "GraphOne", "pricingModel": "usage_based"},
                "collectedAt": "2026-09-11T12:00:00Z",
            },
            {
                "recordType": "RESEARCH_PAPER",
                "schemaVersion": "1.0",
                "source": {"name": "Source", "url": "https://example.com/paper"},
                "content": {
                    "title": "Scaling frontier AI systems",
                    "authors": ["Ada Lovelace"],
                    "paper_url": "https://arxiv.org/abs/1234.0001",
                    "github_url": None,
                    "github_stars": None,
                    "published_date": "2026-09-01",
                },
                "collectedAt": "2026-09-11T12:00:00Z",
            },
            {
                "recordType": "JOB",
                "schemaVersion": "1.0",
                "source": {"name": "Source", "url": "https://example.com/job"},
                "content": {"company": "GraphOne", "date": "2026-09-10", "is_remote": True, "role_family": "research"},
                "collectedAt": "2026-09-11T12:00:00Z",
            },
            {
                "recordType": "NEWS",
                "schemaVersion": "1.0",
                "source": {"name": "Source", "url": "https://example.com/news"},
                "content": {"title": "GraphOne launches new feature", "summary": "A launch announcement.", "published_at": "2026-09-11T00:00:00Z"},
                "collectedAt": "2026-09-11T12:00:00Z",
            },
        ]
    }
    extractor = LLMExtractor(FakeProvider(json.dumps(payload)))

    result = await extractor.extract(source_url="https://example.com/collection", raw_text="A mixed record set.")

    assert result.ok is True
    record_types = {record.recordType for record in result.records}
    assert "STARTUP" in record_types
    assert "PRODUCT" in record_types
    assert "RESEARCH_PAPER" in record_types
    assert "JOB" in record_types
    assert "NEWS" in record_types
    assert all(isinstance(record, (StartupRecord, ProductRecord, ResearchPaperRecord, JobRecord, NewsRecord)) for record in result.records)


@pytest.mark.asyncio
async def test_extractor_is_independent_of_concrete_provider():
    class CustomProvider:
        async def generate(self, prompt: str) -> str:
            return '{"records": [{"recordType": "STARTUP", "schemaVersion": "1.0", "source": {"name": "Custom", "url": "https://example.com/custom"}, "content": {"entityName": "CustomCo"}, "collectedAt": "2026-09-11T12:00:00Z"}]}'

    extractor = LLMExtractor(CustomProvider())
    result = await extractor.extract(source_url="https://example.com/custom", raw_text="Custom provider output.")

    assert result.ok is True
    assert result.records[0].content.entityName == "CustomCo"
