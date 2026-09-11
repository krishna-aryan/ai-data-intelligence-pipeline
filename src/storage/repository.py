from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel

from src.models.schemas import (
    JobRecord,
    NewsRecord,
    ProductRecord,
    ResearchPaperRecord,
    StartupRecord,
)
from src.entity_resolution.models import EntityMappingLog

RECORD_MODELS = {
    "STARTUP": StartupRecord,
    "PRODUCT": ProductRecord,
    "RESEARCH_PAPER": ResearchPaperRecord,
    "JOB": JobRecord,
    "NEWS": NewsRecord,
}


def default_database_path() -> str:
    configured = os.getenv("DATABASE_PATH", "").strip()
    if configured:
        return configured

    repo_root = Path(__file__).resolve().parents[2]
    data_dir = repo_root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return str(data_dir / "pipeline.sqlite3")


def normalize_source_url(value: Any) -> str:
    if value is None:
        return ""

    raw = str(value).strip()
    if not raw:
        return ""

    candidate = raw
    if "://" not in candidate and not candidate.startswith("//"):
        candidate = f"https://{candidate}"

    parsed = urlsplit(candidate)
    scheme = (parsed.scheme or "https").lower()
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        hostname = parsed.netloc.lower().split("@")[-1].split(":", 1)[0]

    port = parsed.port
    netloc = hostname
    if port and port not in {80, 443}:
        netloc = f"{hostname}:{port}"

    path = parsed.path.rstrip("/")
    if path:
        normalized_parts = [part.lower() for part in path.split("/") if part]
        path = "/" + "/".join(normalized_parts)
    else:
        path = ""

    return urlunsplit((scheme, netloc, path, "", ""))


class SQLiteRecordRepository:
    """Deterministic SQLite repository for canonical pipeline records."""

    def __init__(self, database_path: str | Path | None = None) -> None:
        self.database_path = str(Path(database_path) if database_path is not None else default_database_path())
        self._connection = sqlite3.connect(self.database_path, timeout=30.0)
        self._connection.row_factory = sqlite3.Row
        self.initialize()

    def initialize(self) -> None:
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS canonical_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_type TEXT NOT NULL,
                schema_version TEXT NOT NULL,
                source_url TEXT,
                source_url_normalized TEXT NOT NULL,
                source_name TEXT,
                collected_at TEXT NOT NULL,
                published_date TEXT,
                freshness_status TEXT,
                freshness_reason TEXT,
                record_json TEXT NOT NULL,
                UNIQUE(source_url_normalized)
            )
            """
        )
        self._connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_canonical_records_entity_type ON canonical_records(entity_type)"
        )
        self._connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_canonical_records_source_url ON canonical_records(source_url_normalized)"
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS entity_mapping_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_name TEXT NOT NULL,
                normalized_name TEXT NOT NULL,
                canonical_name TEXT,
                canonical_name_key TEXT NOT NULL,
                match_type TEXT NOT NULL,
                reason TEXT NOT NULL,
                source_url TEXT,
                source_url_normalized TEXT NOT NULL,
                UNIQUE(original_name, normalized_name, canonical_name_key, match_type, source_url_normalized)
            )
            """
        )
        self._connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_entity_mapping_logs_source_url ON entity_mapping_logs(source_url_normalized)"
        )
        self._connection.commit()

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()

    def _ensure_record_type(self, record: BaseModel) -> str:
        record_type = str(getattr(record, "recordType", "") or getattr(record, "entity_type", "") or "").strip()
        if not record_type:
            raise ValueError("Record is missing a canonical entity type.")
        if record_type not in RECORD_MODELS:
            raise ValueError(f"Unsupported record type for persistence: {record_type}")
        return record_type

    @staticmethod
    def _utc_iso(value: Any) -> str:
        if value is None:
            return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        if isinstance(value, str):
            return value
        if hasattr(value, "isoformat"):
            dt = value
            if getattr(dt, "tzinfo", None) is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        return str(value)

    def _extract_source_url(self, record: BaseModel) -> str | None:
        source = getattr(record, "source", None)
        if source is not None:
            url_value = getattr(source, "url", None)
            if url_value is not None:
                return str(url_value)

        if hasattr(record, "source_url"):
            value = getattr(record, "source_url")
            if value:
                return str(value)

        content = getattr(record, "content", None)
        if content is not None:
            for candidate in ("source_url", "paper_url", "url", "website"):
                if hasattr(content, candidate):
                    value = getattr(content, candidate)
                    if value:
                        return str(value)

        return None

    def _extract_source_name(self, record: BaseModel) -> str | None:
        source = getattr(record, "source", None)
        if source is not None:
            value = getattr(source, "name", None)
            if value:
                return str(value)
        return None

    def _extract_published_date(self, record: BaseModel) -> str | None:
        if hasattr(record, "published_date"):
            value = getattr(record, "published_date")
            if value is not None:
                return self._utc_iso(value)

        content = getattr(record, "content", None)
        if content is not None:
            for candidate in ("published_at", "published_date", "date", "publicationDate"):
                if hasattr(content, candidate):
                    value = getattr(content, candidate)
                    if value is not None:
                        return self._utc_iso(value)
        return None

    def _extract_freshness(self, record: BaseModel) -> tuple[str | None, str | None]:
        freshness_status = getattr(record, "freshness_status", None)
        freshness_reason = getattr(record, "freshness_reason", None)
        if freshness_status is None and hasattr(record, "content"):
            content = getattr(record, "content")
            freshness_status = getattr(content, "freshness_status", None)
            freshness_reason = getattr(content, "freshness_reason", None)
        return (str(freshness_status) if freshness_status is not None else None,
                str(freshness_reason) if freshness_reason is not None else None)

    def _record_to_row(self, record: BaseModel) -> tuple[str, str, str | None, str, str, str, str | None, str | None, str | None, str]:
        entity_type = self._ensure_record_type(record)
        payload = json.loads(record.model_dump_json())
        source_url = self._extract_source_url(record)
        source_url_normalized = normalize_source_url(source_url)
        source_name = self._extract_source_name(record)
        collected_at = self._utc_iso(getattr(record, "collectedAt", datetime.now(timezone.utc)))
        published_date = self._extract_published_date(record)
        freshness_status, freshness_reason = self._extract_freshness(record)
        json_string = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return (
            entity_type,
            str(getattr(record, "schemaVersion", "1.0")),
            source_url,
            source_url_normalized,
            source_name,
            collected_at,
            published_date,
            freshness_status,
            freshness_reason,
            json_string,
        )

    def upsert_record(self, record: BaseModel) -> BaseModel:
        row = self._record_to_row(record)
        entity_type, schema_version, source_url, source_url_normalized, source_name, collected_at, published_date, freshness_status, freshness_reason, record_json = row

        self._connection.execute(
            """
            INSERT INTO canonical_records (
                entity_type,
                schema_version,
                source_url,
                source_url_normalized,
                source_name,
                collected_at,
                published_date,
                freshness_status,
                freshness_reason,
                record_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_url_normalized)
            DO UPDATE SET
                entity_type = excluded.entity_type,
                schema_version = excluded.schema_version,
                source_url = excluded.source_url,
                source_name = excluded.source_name,
                collected_at = excluded.collected_at,
                published_date = excluded.published_date,
                freshness_status = excluded.freshness_status,
                freshness_reason = excluded.freshness_reason,
                record_json = excluded.record_json
            """,
            (
                entity_type,
                schema_version,
                source_url,
                source_url_normalized,
                source_name,
                collected_at,
                published_date,
                freshness_status,
                freshness_reason,
                record_json,
            ),
        )
        self._connection.commit()
        return record

    def bulk_upsert(self, records: Sequence[BaseModel]) -> list[BaseModel]:
        if not records:
            return []

        try:
            self._connection.execute("BEGIN")
            for record in records:
                if not isinstance(record, BaseModel):
                    raise TypeError("bulk_upsert expects pydantic record instances")
                row = self._record_to_row(record)
                entity_type, schema_version, source_url, source_url_normalized, source_name, collected_at, published_date, freshness_status, freshness_reason, record_json = row
                self._connection.execute(
                    """
                    INSERT INTO canonical_records (
                        entity_type,
                        schema_version,
                        source_url,
                        source_url_normalized,
                        source_name,
                        collected_at,
                        published_date,
                        freshness_status,
                        freshness_reason,
                        record_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(source_url_normalized)
                    DO UPDATE SET
                        entity_type = excluded.entity_type,
                        schema_version = excluded.schema_version,
                        source_url = excluded.source_url,
                        source_name = excluded.source_name,
                        collected_at = excluded.collected_at,
                        published_date = excluded.published_date,
                        freshness_status = excluded.freshness_status,
                        freshness_reason = excluded.freshness_reason,
                        record_json = excluded.record_json
                    """,
                    (
                        entity_type,
                        schema_version,
                        source_url,
                        source_url_normalized,
                        source_name,
                        collected_at,
                        published_date,
                        freshness_status,
                        freshness_reason,
                        record_json,
                    ),
                )
            self._connection.commit()
            return list(records)
        except Exception:
            self._connection.rollback()
            raise

    def get_by_type(self, entity_type: str) -> list[BaseModel]:
        rows = self._connection.execute(
            "SELECT record_json FROM canonical_records WHERE entity_type = ? ORDER BY id ASC",
            (entity_type,),
        ).fetchall()
        return [self._restore_record(row["record_json"]) for row in rows]

    def get_by_source_url(self, source_url: str | None) -> BaseModel | None:
        if source_url is None:
            return None
        normalized = normalize_source_url(source_url)
        if not normalized:
            return None

        row = self._connection.execute(
            "SELECT record_json FROM canonical_records WHERE source_url_normalized = ? LIMIT 1",
            (normalized,),
        ).fetchone()
        if row is None:
            return None
        return self._restore_record(row["record_json"])

    def count_by_type(self, entity_type: str) -> int:
        row = self._connection.execute(
            "SELECT COUNT(*) AS count FROM canonical_records WHERE entity_type = ?",
            (entity_type,),
        ).fetchone()
        return int(row["count"] if row else 0)

    def upsert_mapping_log(self, mapping: EntityMappingLog) -> EntityMappingLog:
        source_url = str(mapping.source_url) if mapping.source_url else None
        source_url_normalized = normalize_source_url(source_url)
        self._connection.execute(
            """
            INSERT INTO entity_mapping_logs (
                original_name, normalized_name, canonical_name, canonical_name_key, match_type,
                reason, source_url, source_url_normalized
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(original_name, normalized_name, canonical_name_key, match_type, source_url_normalized)
            DO UPDATE SET reason = excluded.reason, source_url = excluded.source_url
            """,
            (
                mapping.original_name,
                mapping.normalized_name,
                mapping.canonical_name,
                mapping.canonical_name or "",
                mapping.match_type,
                mapping.reason,
                source_url,
                source_url_normalized,
            ),
        )
        self._connection.commit()
        return mapping

    def get_mapping_logs(self, *, source_url: str | None = None) -> list[EntityMappingLog]:
        if source_url is None:
            rows = self._connection.execute(
                "SELECT original_name, normalized_name, canonical_name, match_type, reason, source_url FROM entity_mapping_logs ORDER BY id ASC"
            ).fetchall()
        else:
            rows = self._connection.execute(
                "SELECT original_name, normalized_name, canonical_name, match_type, reason, source_url FROM entity_mapping_logs WHERE source_url_normalized = ? ORDER BY id ASC",
                (normalize_source_url(source_url),),
            ).fetchall()
        return [EntityMappingLog.model_validate(dict(row)) for row in rows]

    def count_mapping_logs(self) -> int:
        row = self._connection.execute("SELECT COUNT(*) AS count FROM entity_mapping_logs").fetchone()
        return int(row["count"] if row else 0)

    @staticmethod
    def _restore_record(record_json: str) -> BaseModel:
        payload = json.loads(record_json)
        model_cls = RECORD_MODELS.get(str(payload.get("recordType")), BaseModel)
        if model_cls is BaseModel:
            return BaseModel.model_validate(payload)
        return model_cls.model_validate(payload)


__all__ = ["SQLiteRecordRepository", "default_database_path", "normalize_source_url"]
