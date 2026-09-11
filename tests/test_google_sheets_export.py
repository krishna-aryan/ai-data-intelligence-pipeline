from datetime import datetime, timezone

import pytest

from src.entity_resolution.models import EntityMappingLog
from src.integrations.google_sheets import (
    GoogleSheetsExporter,
    SheetsAPIError,
    SheetsAuthenticationError,
    SheetsConfigurationError,
    WORKSHEET_NAMES,
)
from src.models.schemas import (
    JobContent,
    JobRecord,
    NewsContent,
    NewsRecord,
    ProductContent,
    ProductRecord,
    ResearchPaperContent,
    ResearchPaperRecord,
    SourceInfo,
    StartupContent,
    StartupRecord,
)
from src.storage.repository import SQLiteRecordRepository


class FakeSheetsClient:
    def __init__(self):
        self.sheets = {}
        self.calls = []
        self.failure = None

    def ensure_worksheet(self, spreadsheet_id, worksheet_name):
        self.calls.append(("ensure", spreadsheet_id, worksheet_name))
        if self.failure:
            raise self.failure
        self.sheets.setdefault(worksheet_name, [])

    def replace_values(self, spreadsheet_id, worksheet_name, values):
        self.calls.append(("replace", spreadsheet_id, worksheet_name))
        if self.failure:
            raise self.failure
        self.sheets[worksheet_name] = [list(row) for row in values]


def seed_repository(tmp_path):
    repo = SQLiteRecordRepository(tmp_path / "pipeline.sqlite3")
    collected = datetime(2026, 9, 11, 12, tzinfo=timezone.utc)
    repo.bulk_upsert([
        StartupRecord(schemaVersion="1.0", recordType="STARTUP", source=SourceInfo(name="Feed", url="https://example.com/z"), content=StartupContent(entityName="Open AI", employeeCount=10), collectedAt=collected),
        ProductRecord(schemaVersion="1.0", recordType="PRODUCT", source=SourceInfo(name="Feed", url="https://example.com/a"), content=ProductContent(startupName="Anthropic", pricingModel="usage_based"), collectedAt=collected),
        ResearchPaperRecord(schemaVersion="1.0", recordType="RESEARCH_PAPER", source=SourceInfo(name="Papers", url="https://example.com/paper"), content=ResearchPaperContent(title="Paper", authors=["Author"], paper_url="https://papers.example/paper"), collectedAt=collected),
        JobRecord(schemaVersion="1.0", recordType="JOB", source=SourceInfo(name="Jobs", url="https://example.com/job"), content=JobContent(company="Company", date="2026-09-10", role_family="Engineer"), collectedAt=collected),
        NewsRecord(schemaVersion="1.0", recordType="NEWS", source=SourceInfo(name="News", url="https://example.com/news"), content=NewsContent(title="Headline", summary="Summary"), collectedAt=collected),
    ])
    repo.upsert_mapping_log(EntityMappingLog(original_name="Open AI", normalized_name="open ai", canonical_name="OpenAI", match_type="exact_alias", reason="deterministic", source_url="https://example.com/z"))
    return repo


def test_all_required_worksheets_and_deterministic_columns(tmp_path):
    repo = seed_repository(tmp_path)
    client = FakeSheetsClient()
    result = GoogleSheetsExporter(repo, client, spreadsheet_id="sheet-1").export()

    assert tuple(client.sheets) == WORKSHEET_NAMES
    assert tuple(item.worksheet_name for item in result.worksheets) == WORKSHEET_NAMES
    assert client.sheets["Startups"][0] == ["entity_name", "employee_count", "resolved_canonical_name", "resolution_match_type", "resolution_reason", "source_name", "source_url", "collected_at", "freshness_status", "freshness_reason"]
    assert client.sheets["Entity Mapping Log"][0] == ["original_name", "normalized_name", "canonical_name", "match_type", "reason", "source_url"]


def test_rows_are_sorted_and_repeated_export_is_idempotent(tmp_path):
    repo = seed_repository(tmp_path)
    client = FakeSheetsClient()
    exporter = GoogleSheetsExporter(repo, client, spreadsheet_id="sheet-1")

    first = exporter.export()
    first_snapshot = {name: list(values) for name, values in client.sheets.items()}
    second = exporter.export()

    assert first == second
    assert client.sheets == first_snapshot
    assert client.sheets["Startups"][1][6] == "https://example.com/z"
    assert sum(call[0] == "replace" for call in client.calls) == 12


def test_empty_datasets_export_headers_only(tmp_path):
    repo = SQLiteRecordRepository(tmp_path / "empty.sqlite3")
    client = FakeSheetsClient()

    result = GoogleSheetsExporter(repo, client, spreadsheet_id="sheet-1").export()

    assert result.total_rows == 0
    assert all(len(values) == 1 for values in client.sheets.values())


def test_mapping_log_and_source_url_are_exported(tmp_path):
    repo = seed_repository(tmp_path)
    client = FakeSheetsClient()

    GoogleSheetsExporter(repo, client, spreadsheet_id="sheet-1").export()

    assert client.sheets["Entity Mapping Log"][1][-1] == "https://example.com/z"
    assert client.sheets["Startups"][1][6] == "https://example.com/z"


def test_invalid_configuration_fails_without_client_call(tmp_path):
    repo = SQLiteRecordRepository(tmp_path / "config.sqlite3")
    client = FakeSheetsClient()

    with pytest.raises(SheetsConfigurationError):
        GoogleSheetsExporter(repo, client, spreadsheet_id=" ")
    assert client.calls == []


def test_authentication_failure_is_structured_and_does_not_leak_credentials(tmp_path):
    repo = SQLiteRecordRepository(tmp_path / "auth.sqlite3")
    client = FakeSheetsClient()
    client.failure = PermissionError("credential-content-should-not-appear")

    with pytest.raises(SheetsAuthenticationError) as excinfo:
        GoogleSheetsExporter(repo, client, spreadsheet_id="sheet-1").export()

    assert "credential-content" not in str(excinfo.value)


def test_api_failure_is_structured_and_does_not_leak_credentials(tmp_path):
    repo = SQLiteRecordRepository(tmp_path / "api.sqlite3")
    client = FakeSheetsClient()
    client.failure = RuntimeError("secret-api-key")

    with pytest.raises(SheetsAPIError) as excinfo:
        GoogleSheetsExporter(repo, client, spreadsheet_id="sheet-1").export()

    assert "secret-api-key" not in str(excinfo.value)
