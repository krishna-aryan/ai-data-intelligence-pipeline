from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, ValidationError

from src.models.schemas import (
    JobRecord,
    NewsRecord,
    ProductRecord,
    ResearchPaperRecord,
    SourceInfo,
    StartupRecord,
)

from .base import LLMProvider
from .models import CanonicalRecord, ExtractionFailure, ExtractionResult


class LLMExtractor:
    """Convert raw source text into canonical validated project records."""

    def __init__(self, provider: LLMProvider, *, prompt_template: str | None = None) -> None:
        self.provider = provider
        self.prompt_template = prompt_template or self._default_prompt()

    async def extract(
        self,
        *,
        source_url: str,
        raw_text: str,
        source_name: str = "source",
    ) -> ExtractionResult | ExtractionFailure:
        if not raw_text or not raw_text.strip():
            return ExtractionFailure(
                error_type="empty_response",
                message="Raw source text is empty.",
                source_url=source_url,
            )

        prompt = self._build_prompt(source_url=source_url, raw_text=raw_text)

        try:
            raw_response = await self.provider.generate(prompt)
        except Exception as exc:  # pragma: no cover - provider implementations vary
            return ExtractionFailure(
                error_type="provider_failure",
                message=f"LLM provider failure: {exc}",
                source_url=source_url,
            )

        response_text = self._normalize_response(raw_response)
        if not response_text:
            return ExtractionFailure(
                error_type="empty_response",
                message="Provider returned an empty response.",
                source_url=source_url,
            )

        try:
            payload = json.loads(response_text)
        except json.JSONDecodeError as exc:
            return ExtractionFailure(
                error_type="invalid_json",
                message=f"Provider response was not valid JSON: {exc}",
                source_url=source_url,
            )

        try:
            records = self._normalize_records(payload)
        except ValueError as exc:
            return ExtractionFailure(
                error_type="schema_validation_failure",
                message=f"Extraction payload was malformed: {exc}",
                source_url=source_url,
            )

        if not records:
            return ExtractionFailure(
                error_type="empty_response",
                message="No extraction records were returned by the model.",
                source_url=source_url,
            )

        validated_records: list[CanonicalRecord] = []
        for item in records:
            try:
                record = self._validate_record(item=item, source_url=source_url, source_name=source_name)
            except ValidationError as exc:
                return ExtractionFailure(
                    error_type="schema_validation_failure",
                    message=f"Schema validation failed for extracted record: {exc}",
                    source_url=source_url,
                )
            validated_records.append(record)

        return ExtractionResult(
            source_url=source_url,
            records=validated_records,
            created_at=datetime.now(UTC),
        )

    def _build_prompt(self, *, source_url: str, raw_text: str) -> str:
        return self.prompt_template.format(source_url=source_url, raw_text=raw_text)

    def _normalize_response(self, response: str) -> str:
        text = response.strip()
        if text.startswith("```") and text.endswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:].lstrip()
        return text.strip()

    def _normalize_records(self, payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]

        if isinstance(payload, dict):
            for key in ("records", "entities", "items", "results"):
                value = payload.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
            if self._looks_like_record(payload):
                return [payload]

        raise ValueError("Extraction payload must be a list or a dict containing records.")

    def _looks_like_record(self, payload: dict[str, Any]) -> bool:
        return bool(payload.get("recordType")) or any(key in payload for key in ("entityName", "startupName", "company", "title"))

    def _validate_record(
        self,
        *,
        item: dict[str, Any],
        source_url: str,
        source_name: str,
    ) -> CanonicalRecord:
        data = dict(item)

        if "source" not in data or data["source"] is None:
            data["source"] = {"name": source_name or "source", "url": source_url}
        elif isinstance(data["source"], dict):
            data["source"] = {
                "name": data["source"].get("name") or source_name or "source",
                "url": source_url,
            }
        else:
            data["source"] = {"name": source_name or "source", "url": source_url}

        data.setdefault("schemaVersion", "1.0")
        data.setdefault("collectedAt", datetime.now(UTC).isoformat(timespec="seconds"))

        if data.get("recordType") == "STARTUP":
            return StartupRecord.model_validate(data)
        if data.get("recordType") == "PRODUCT":
            return ProductRecord.model_validate(data)
        if data.get("recordType") == "RESEARCH_PAPER":
            return ResearchPaperRecord.model_validate(data)
        if data.get("recordType") == "JOB":
            return JobRecord.model_validate(data)
        if data.get("recordType") == "NEWS":
            return NewsRecord.model_validate(data)

        raise ValidationError.from_exception_data(
            title="Unknown record type",
            line_errors=[
                {
                    "type": "literal_error",
                    "loc": ("recordType",),
                    "input": data.get("recordType"),
                    "url": "https://errors.pydantic.dev/2.0.0/v/literal_error",
                }
            ],
        )

    def _default_prompt(self) -> str:
        return """You are a strict data extraction engine.

Task:
- Read the raw source text below.
- Extract only facts explicitly stated in the text.
- Use null for missing information.
- Never invent values, estimate claims, or infer unsupported facts.
- Preserve the exact source URL: {source_url}.
- Do not replace or invent the source URL.
- Return JSON only.
- Use this exact JSON schema:
{{
  "records": [
    {{
      "recordType": "STARTUP|PRODUCT|RESEARCH_PAPER|JOB|NEWS",
      "schemaVersion": "1.0",
      "source": {{"name": "source", "url": "{source_url}"}},
      "content": {{ ... }},
      "collectedAt": "ISO8601 timestamp"
    }}
  ]
}}

Rules:
- Only include information explicitly supported by the source text.
- If a field is unavailable, set it to null.
- Do not fabricate names, dates, URLs, pricing, company names, titles, citations, or statistics.
- Use valid JSON with double quotes around keys and string values.
- Do not include markdown fences or explanations.

Source URL:
{source_url}

Source text:
{raw_text}
"""


__all__ = ["LLMExtractor"]
