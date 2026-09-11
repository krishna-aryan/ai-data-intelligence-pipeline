from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Iterable, Mapping

from pydantic import BaseModel, Field

from src.batch import BoundedBatchProcessor
from src.config.settings import load_settings
from src.entity_resolution import EntityResolver
from src.entity_resolution.models import EntityMappingLog, ResolutionResult
from src.llm import LLMExtractor
from src.models.schemas import EntityResolutionMetadata
from src.storage.repository import SQLiteRecordRepository


class _NullLLMProvider:
    provider_name = "null"

    async def generate(self, prompt: str) -> str:
        raise RuntimeError("No LLM provider configured for pipeline processing.")


class _PipelineRecordFailure(Exception):
    def __init__(self, failure: dict[str, Any]) -> None:
        self.failure = failure
        super().__init__(failure.get("message", "Pipeline record failed."))


class PipelineBatchResult(BaseModel):
    total: int = 0
    processed: int = 0
    stored: int = 0
    failed: int = 0
    succeeded: int = 0
    skipped: int = 0
    duration_seconds: float = 0.0
    successes: list[dict[str, Any]] = Field(default_factory=list)
    failures: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PipelineOrchestrator:
    """Small deterministic orchestration layer for local ingestion, extraction, and storage."""

    def __init__(
        self,
        repository: SQLiteRecordRepository | None = None,
        *,
        llm_provider: Any | None = None,
        entity_resolver: EntityResolver | None = None,
        extractor: LLMExtractor | None = None,
        batch_concurrency: int | None = None,
    ) -> None:
        self.repository = repository or SQLiteRecordRepository()
        self.llm_provider = llm_provider or _NullLLMProvider()
        self.entity_resolver = entity_resolver or EntityResolver()
        self.extractor = extractor or LLMExtractor(self.llm_provider)
        self.batch_concurrency = batch_concurrency if batch_concurrency is not None else load_settings().batch_concurrency

    async def process_batch(
        self,
        records: Iterable[Mapping[str, Any] | Any],
        *,
        provider_response_overrides: dict[str, str] | None = None,
    ) -> PipelineBatchResult:
        result = PipelineBatchResult(total=0, processed=0, stored=0, failed=0)
        overrides = provider_response_overrides or {}

        async def handle(item: Mapping[str, Any] | Any) -> dict[str, Any]:
            record_result = await self.process_record(item, provider_response_overrides=overrides)
            if not record_result.get("ok"):
                raise _PipelineRecordFailure(record_result["failure"])
            return record_result

        execution = await BoundedBatchProcessor[Mapping[str, Any] | Any, dict[str, Any]](
            self.batch_concurrency
        ).process(records, handle, skip_if=self._is_skipped)
        result.total = execution.statistics.total
        result.succeeded = execution.statistics.succeeded
        result.failed = execution.statistics.failed
        result.skipped = execution.statistics.skipped
        result.duration_seconds = execution.statistics.duration_seconds
        result.processed = result.succeeded
        for item_result in execution.items:
            if item_result.skipped:
                continue
            if item_result.ok and item_result.value is not None:
                record_result = item_result.value
                result.stored += int(record_result.get("stored", 0))
                result.successes.append(record_result["summary"])
            else:
                failure = getattr(item_result.error, "failure", None)
                result.failures.append(failure or {
                    "source_url": self._safe_source_url(item_result.item),
                    "error_type": type(item_result.error).__name__ if item_result.error else "unknown_error",
                    "message": str(item_result.error) if item_result.error else "Unknown batch failure.",
                })

        return result

    @staticmethod
    def _is_skipped(item: Mapping[str, Any] | Any) -> bool:
        return isinstance(item, Mapping) and bool(item.get("skip", False))

    @staticmethod
    def _safe_source_url(item: Mapping[str, Any] | Any) -> str:
        if isinstance(item, Mapping):
            return str(item.get("source_url") or item.get("url") or "")
        return str(getattr(item, "source_url", ""))

    async def process_record(
        self,
        item: Mapping[str, Any] | Any,
        *,
        provider_response_overrides: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        request = self._coerce_request(item)
        source_url = request["source_url"]
        raw_text = request["raw_text"]
        source_name = request.get("source_name") or "source"

        override = (provider_response_overrides or {}).get(source_url)
        extractor = self.extractor
        if override is not None:
            extractor = LLMExtractor(_StaticResponseProvider(override))

        extraction = await extractor.extract(source_url=source_url, raw_text=raw_text, source_name=source_name)
        if not getattr(extraction, "ok", False):
            return {
                "ok": False,
                "failure": {
                    "source_url": source_url,
                    "error_type": getattr(extraction, "error_type", "unknown_error"),
                    "message": getattr(extraction, "message", "Unknown extraction failure."),
                },
            }

        persisted_records: list[Any] = []
        for record in extraction.records:
            resolution = self._resolve_record_identity(record, source_url=source_url)
            if resolution is not None:
                self._attach_resolution_metadata(record, resolution, source_url=source_url)
                self.repository.upsert_mapping_log(self.entity_resolver.build_mapping_log(resolution, source_url=source_url))
            self.repository.upsert_record(record)
            persisted_records.append(record)

        summary = {
            "source_url": source_url,
            "source_name": source_name,
            "record_types": [getattr(record, "recordType", "UNKNOWN") for record in extraction.records],
            "stored": len(persisted_records),
        }
        return {
            "ok": True,
            "stored": len(persisted_records),
            "summary": summary,
        }

    def _coerce_request(self, item: Mapping[str, Any] | Any) -> dict[str, Any]:
        if isinstance(item, Mapping):
            source_url = str(item.get("source_url") or item.get("url") or "").strip()
            raw_text = item.get("raw_text") or item.get("text") or ""
            source_name = item.get("source_name") or item.get("source") or "source"
            if not source_url:
                raise ValueError("Pipeline record is missing a source_url.")
            return {"source_url": source_url, "raw_text": str(raw_text), "source_name": str(source_name)}

        if hasattr(item, "source_url") and hasattr(item, "raw_text"):
            return {
                "source_url": str(item.source_url),
                "raw_text": str(item.raw_text),
                "source_name": getattr(item, "source_name", "source"),
            }

        raise ValueError("Unsupported pipeline input type; expected a mapping or object with source_url/raw_text.")

    def _resolve_record_identity(self, record: Any, *, source_url: str) -> ResolutionResult | None:
        if not hasattr(record, "recordType"):
            return None

        content = getattr(record, "content", None)
        if content is None:
            return None

        name = None
        if getattr(record, "recordType", None) == "STARTUP":
            name = getattr(content, "entityName", None)
            if name:
                return self.entity_resolver.resolve_startup(str(name), source_url=source_url)
        elif getattr(record, "recordType", None) == "PRODUCT":
            name = getattr(content, "startupName", None)
            if name:
                return self.entity_resolver.resolve_product(str(name), source_url=source_url)

        return None

    @staticmethod
    def _attach_resolution_metadata(record: Any, resolution: ResolutionResult, *, source_url: str) -> None:
        content = getattr(record, "content", None)
        if content is None or not hasattr(content, "entityResolution"):
            return
        content.entityResolution = EntityResolutionMetadata(
            original_name=resolution.original_name,
            normalized_name=resolution.normalized_name,
            canonical_name=resolution.canonical_name,
            match_type=resolution.match_type,
            reason=resolution.reason,
            source_url=source_url,
        )


class _StaticResponseProvider:
    def __init__(self, response: str) -> None:
        self.response = response
        self.provider_name = "override"

    async def generate(self, prompt: str) -> str:
        return self.response


__all__ = ["PipelineBatchResult", "PipelineOrchestrator"]
