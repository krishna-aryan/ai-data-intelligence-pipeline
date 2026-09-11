from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel

from src.storage.repository import SQLiteRecordRepository, normalize_source_url


WORKSHEET_NAMES = (
    "Startups",
    "Products",
    "Research Papers",
    "Jobs",
    "News",
    "Entity Mapping Log",
)


class GoogleSheetsClient(Protocol):
    def ensure_worksheet(self, spreadsheet_id: str, worksheet_name: str) -> None: ...

    def replace_values(self, spreadsheet_id: str, worksheet_name: str, values: list[list[Any]]) -> None: ...


class SheetsExportError(RuntimeError):
    pass


class SheetsConfigurationError(SheetsExportError):
    pass


class SheetsAuthenticationError(SheetsExportError):
    pass


class SheetsAPIError(SheetsExportError):
    pass


class SheetsDataError(SheetsExportError):
    pass


@dataclass(frozen=True)
class WorksheetExportResult:
    worksheet_name: str
    row_count: int


@dataclass(frozen=True)
class GoogleSheetsExportResult:
    spreadsheet_id: str
    worksheets: tuple[WorksheetExportResult, ...]

    @property
    def total_rows(self) -> int:
        return sum(item.row_count for item in self.worksheets)


class GoogleSheetsExporter:
    def __init__(
        self,
        repository: SQLiteRecordRepository,
        client: GoogleSheetsClient,
        *,
        spreadsheet_id: str | None,
    ) -> None:
        if not spreadsheet_id or not spreadsheet_id.strip():
            raise SheetsConfigurationError("GOOGLE_SHEETS_SPREADSHEET_ID is required.")
        self.repository = repository
        self.client = client
        self.spreadsheet_id = spreadsheet_id.strip()

    def export(self) -> GoogleSheetsExportResult:
        exports = (
            ("Startups", "STARTUP", self._startup_rows),
            ("Products", "PRODUCT", self._product_rows),
            ("Research Papers", "RESEARCH_PAPER", self._research_rows),
            ("Jobs", "JOB", self._job_rows),
            ("News", "NEWS", self._news_rows),
        )
        results: list[WorksheetExportResult] = []
        try:
            for worksheet_name, record_type, row_builder in exports:
                values = row_builder(self.repository.get_by_type(record_type))
                self._write(worksheet_name, values)
                results.append(WorksheetExportResult(worksheet_name, max(0, len(values) - 1)))
            mapping_values = self._mapping_rows(self.repository.get_mapping_logs())
            self._write("Entity Mapping Log", mapping_values)
            results.append(WorksheetExportResult("Entity Mapping Log", max(0, len(mapping_values) - 1)))
        except SheetsExportError:
            raise
        except Exception as exc:
            raise SheetsAPIError("Google Sheets export failed.") from exc
        return GoogleSheetsExportResult(self.spreadsheet_id, tuple(results))

    def _write(self, worksheet_name: str, values: list[list[Any]]) -> None:
        try:
            self.client.ensure_worksheet(self.spreadsheet_id, worksheet_name)
            self.client.replace_values(self.spreadsheet_id, worksheet_name, values)
        except SheetsExportError:
            raise
        except (PermissionError, KeyError) as exc:
            raise SheetsAuthenticationError("Google Sheets authentication failed.") from exc
        except Exception as exc:
            raise SheetsAPIError(f"Google Sheets API request failed for {worksheet_name}.") from exc

    @staticmethod
    def _source(record: BaseModel) -> tuple[str, str]:
        source = getattr(record, "source", None)
        if source is None:
            return "", ""
        return str(getattr(source, "name", "") or ""), str(getattr(source, "url", "") or "")

    @staticmethod
    def _freshness(record: BaseModel) -> tuple[str, str]:
        content = getattr(record, "content", None)
        return (
            str(getattr(content, "freshness_status", "") or ""),
            str(getattr(content, "freshness_reason", "") or ""),
        )

    @staticmethod
    def _resolution(record: BaseModel) -> tuple[str, str, str, str]:
        content = getattr(record, "content", None)
        resolution = getattr(content, "entityResolution", None)
        if resolution is None:
            return "", "", "", ""
        return (
            str(getattr(resolution, "canonical_name", "") or ""),
            str(getattr(resolution, "match_type", "") or ""),
            str(getattr(resolution, "reason", "") or ""),
            str(getattr(resolution, "original_name", "") or ""),
        )

    @classmethod
    def _startup_rows(cls, records: list[BaseModel]) -> list[list[Any]]:
        header = ["entity_name", "employee_count", "resolved_canonical_name", "resolution_match_type", "resolution_reason", "source_name", "source_url", "collected_at", "freshness_status", "freshness_reason"]
        rows = []
        for record in records:
            source_name, source_url = cls._source(record)
            resolution = cls._resolution(record)
            status, reason = cls._freshness(record)
            rows.append([record.content.entityName, record.content.employeeCount or "", resolution[0], resolution[1], resolution[2], source_name, source_url, str(record.collectedAt), status, reason])
        return [header, *sorted(rows, key=lambda row: (normalize_source_url(row[6]), row[0]))]

    @classmethod
    def _product_rows(cls, records: list[BaseModel]) -> list[list[Any]]:
        header = ["startup_name", "pricing_model", "resolved_canonical_name", "resolution_match_type", "resolution_reason", "source_name", "source_url", "collected_at", "freshness_status", "freshness_reason"]
        rows = []
        for record in records:
            source_name, source_url = cls._source(record)
            resolution = cls._resolution(record)
            status, reason = cls._freshness(record)
            rows.append([record.content.startupName, record.content.pricingModel or "", resolution[0], resolution[1], resolution[2], source_name, source_url, str(record.collectedAt), status, reason])
        return [header, *sorted(rows, key=lambda row: (normalize_source_url(row[6]), row[0]))]

    @classmethod
    def _research_rows(cls, records: list[BaseModel]) -> list[list[Any]]:
        header = ["title", "authors", "paper_url", "github_url", "github_stars", "published_date", "source_name", "source_url", "collected_at", "freshness_status", "freshness_reason"]
        rows = []
        for record in records:
            source_name, source_url = cls._source(record)
            status, reason = cls._freshness(record)
            content = record.content
            rows.append([content.title, ", ".join(content.authors), str(content.paper_url), str(content.github_url or ""), content.github_stars or "", str(content.published_date or ""), source_name, source_url, str(record.collectedAt), status, reason])
        return [header, *sorted(rows, key=lambda row: (normalize_source_url(row[7]), row[0]))]

    @classmethod
    def _job_rows(cls, records: list[BaseModel]) -> list[list[Any]]:
        header = ["company", "date", "is_remote", "role_family", "source_name", "source_url", "collected_at", "freshness_status", "freshness_reason"]
        rows = []
        for record in records:
            source_name, source_url = cls._source(record)
            status, reason = cls._freshness(record)
            content = record.content
            rows.append([content.company, str(content.date), content.is_remote, content.role_family, source_name, source_url, str(record.collectedAt), status, reason])
        return [header, *sorted(rows, key=lambda row: (normalize_source_url(row[5]), row[0]))]

    @classmethod
    def _news_rows(cls, records: list[BaseModel]) -> list[list[Any]]:
        header = ["title", "summary", "published_at", "source_name", "source_url", "collected_at", "freshness_status", "freshness_reason"]
        rows = []
        for record in records:
            source_name, source_url = cls._source(record)
            status, reason = cls._freshness(record)
            content = record.content
            rows.append([content.title, content.summary or "", str(content.published_at or ""), source_name, source_url, str(record.collectedAt), status, reason])
        return [header, *sorted(rows, key=lambda row: (normalize_source_url(row[4]), row[0]))]

    @staticmethod
    def _mapping_rows(mappings: list[BaseModel]) -> list[list[Any]]:
        header = ["original_name", "normalized_name", "canonical_name", "match_type", "reason", "source_url"]
        rows = [[item.original_name, item.normalized_name, item.canonical_name or "", item.match_type, item.reason, item.source_url or ""] for item in mappings]
        return [header, *sorted(rows, key=lambda row: (normalize_source_url(row[5]), row[1], row[0]))]


__all__ = [
    "GoogleSheetsClient",
    "GoogleSheetsExportResult",
    "GoogleSheetsExporter",
    "SheetsAPIError",
    "SheetsAuthenticationError",
    "SheetsConfigurationError",
    "SheetsDataError",
    "SheetsExportError",
    "WORKSHEET_NAMES",
    "WorksheetExportResult",
]
