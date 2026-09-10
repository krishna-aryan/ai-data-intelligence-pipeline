from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Iterable

from bs4 import BeautifulSoup

from .models import DateParseResult


RELATIVE_PATTERNS = [
    (r"(?P<amount>\d+)\s*(?:hours?|hrs?|hr)\s+ago", "hours"),
    (r"(?P<amount>\d+)\s*(?:minutes?|mins?|min)\s+ago", "minutes"),
    (r"(?P<amount>\d+)\s*(?:days?|d)\s+ago", "days"),
]


def _coerce_reference_time(reference_time: Any) -> datetime:
    if reference_time is None:
        raise ValueError("reference_time is required")
    if isinstance(reference_time, datetime):
        dt = reference_time
    elif isinstance(reference_time, date):
        dt = datetime.combine(reference_time, datetime.min.time())
    else:
        raise TypeError("reference_time must be a datetime or date")

    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _normalize_to_utc(value: datetime | date, *, raw_value: Any) -> tuple[datetime, str | None, str]:
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc), "naive datetime assumed UTC", "parsed"
        return dt.astimezone(timezone.utc), "timezone-aware datetime normalized to UTC", "parsed"

    if isinstance(value, date):
        dt = datetime.combine(value, datetime.min.time(), tzinfo=timezone.utc)
        return dt, "date assumed at 00:00:00 UTC", "parsed"

    raise TypeError(f"Unsupported date value: {raw_value!r}")


def _parse_relative_expression(raw_value: str, reference_time: datetime) -> tuple[datetime | None, str | None, str | None]:
    candidate = raw_value.strip().lower()
    if not candidate:
        return None, None, None

    if candidate == "yesterday":
        return reference_time - timedelta(days=1), "relative expression: yesterday", "relative"

    if candidate == "today":
        return reference_time, "relative expression: today", "relative"

    for pattern, unit in RELATIVE_PATTERNS:
        match = re.fullmatch(pattern, candidate)
        if not match:
            continue
        amount = int(match.group("amount"))
        if unit == "hours":
            delta = timedelta(hours=amount)
        elif unit == "minutes":
            delta = timedelta(minutes=amount)
        elif unit == "days":
            delta = timedelta(days=amount)
        else:
            continue
        return reference_time - delta, "relative expression", "relative"

    return None, None, None


def _try_parse_datetime(raw_value: Any) -> tuple[datetime | None, str | None]:
    if isinstance(raw_value, datetime):
        return _normalize_to_utc(raw_value, raw_value=raw_value)[:2]

    if isinstance(raw_value, date):
        return _normalize_to_utc(raw_value, raw_value=raw_value)[:2]

    if not isinstance(raw_value, str):
        return None, None

    value = raw_value.strip()
    if not value:
        return None, None

    if value.lower() in {"yesterday", "today"}:
        return None, None

    if value.endswith("Z"):
        value = value[:-1] + "+00:00"

    candidates = []
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S.%f%z",
        "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%b %d, %Y",
        "%b %d, %Y %H:%M:%S",
        "%B %d, %Y",
        "%B %d, %Y %H:%M:%S",
        "%d %b %Y",
        "%d %b %Y %H:%M:%S",
        "%d %B %Y",
        "%d %B %Y %H:%M:%S",
    ):
        candidates.append(fmt)

    for fmt in candidates:
        try:
            dt = datetime.strptime(value, fmt)
            return _normalize_to_utc(dt, raw_value=raw_value)[:2]
        except ValueError:
            continue

    try:
        dt = datetime.fromisoformat(value)
        return _normalize_to_utc(dt, raw_value=raw_value)[:2]
    except ValueError:
        pass

    try:
        dt = parsedate_to_datetime(value)
        if dt is not None:
            return _normalize_to_utc(dt, raw_value=raw_value)[:2]
    except (TypeError, ValueError, IndexError):
        pass

    return None, None


def parse_publication_date(raw_value: Any, reference_time: Any) -> DateParseResult:
    if raw_value is None or (isinstance(raw_value, str) and raw_value.strip() == ""):
        return DateParseResult(
            original_value=raw_value,
            normalized_datetime=None,
            parsing_method="missing",
            timezone_assumption=None,
            status="missing",
            reason="Publication date is missing.",
        )

    reference_dt = _coerce_reference_time(reference_time)
    raw_text = raw_value if isinstance(raw_value, str) else str(raw_value)
    raw_text = raw_text.strip()
    if not raw_text:
        return DateParseResult(
            original_value=raw_value,
            normalized_datetime=None,
            parsing_method="missing",
            timezone_assumption=None,
            status="missing",
            reason="Publication date is empty.",
        )

    if isinstance(raw_value, datetime) or isinstance(raw_value, date):
        dt, assumption, _ = _normalize_to_utc(raw_value, raw_value=raw_value)
        return DateParseResult(
            original_value=raw_value,
            normalized_datetime=dt,
            parsing_method="direct_datetime",
            timezone_assumption=assumption,
            status="parsed",
            reason="Direct datetime value accepted.",
        )

    relative_dt, relative_assumption, relative_method = _parse_relative_expression(raw_text, reference_dt)
    if relative_dt is not None:
        return DateParseResult(
            original_value=raw_value,
            normalized_datetime=relative_dt.astimezone(timezone.utc),
            parsing_method=relative_method or "relative",
            timezone_assumption="relative date calculated from supplied reference time in UTC",
            status="parsed",
            reason=relative_assumption or "Relative date resolved from the supplied reference time.",
        )

    dt, assumption = _try_parse_datetime(raw_text)
    if dt is not None:
        return DateParseResult(
            original_value=raw_value,
            normalized_datetime=dt,
            parsing_method="iso8601 or common date parser",
            timezone_assumption=assumption or "timezone normalized to UTC",
            status="parsed",
            reason="Date value parsed successfully.",
        )

    return DateParseResult(
        original_value=raw_value,
        normalized_datetime=None,
        parsing_method="string_parser",
        timezone_assumption=None,
        status="unparseable",
        reason="Date value is not recognized as an absolute or relative publication date.",
    )


def _extract_jsonld_dates(payload: Any) -> list[str]:
    values: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key == "datePublished":
                if isinstance(value, str):
                    values.append(value)
            else:
                values.extend(_extract_jsonld_dates(value))
    elif isinstance(payload, list):
        for item in payload:
            values.extend(_extract_jsonld_dates(item))
    return values


def _extract_visible_date_candidates(text: str) -> list[str]:
    candidate_patterns = [
        r"\b\d{4}-\d{2}-\d{2}(?:[T\s]\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:?\d{2})?)?\b",
        r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},\s+\d{4}\b",
        r"\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}\b",
        r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*,\s+\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}\b",
    ]
    candidates: list[str] = []
    for pattern in candidate_patterns:
        matches = re.findall(pattern, text, flags=re.IGNORECASE)
        for match in matches:
            if match:
                candidates.append(match)
    return candidates


def extract_publication_date(source: Any, reference_time: Any) -> DateParseResult:
    if source is None:
        return parse_publication_date(None, reference_time)

    if not isinstance(source, str):
        return parse_publication_date(source, reference_time)

    text = source.strip()
    if not text:
        return parse_publication_date("", reference_time)

    soup = BeautifulSoup(text, "html.parser")
    buckets: list[str] = []

    for script in soup.find_all("script", type="application/ld+json"):
        script_text = script.string or script.get_text(" ", strip=True)
        if not script_text:
            continue
        try:
            payload = json.loads(script_text)
        except json.JSONDecodeError:
            continue
        buckets.extend(_extract_jsonld_dates(payload))

    for selector in ['meta[property="article:published_time"]', 'meta[property="article:published" ]', 'meta[name="date"]', 'meta[name="pubdate"]', 'meta[property="pubdate"]']:
        for tag in soup.select(selector):
            content = (tag.get("content") or tag.get("datetime") or "").strip()
            if content:
                buckets.append(content)

    for tag in soup.find_all("time"):
        datetime_value = (tag.get("datetime") or "").strip()
        if datetime_value:
            buckets.append(datetime_value)

    visible_text = soup.get_text(" ", strip=True)
    buckets.extend(_extract_visible_date_candidates(visible_text))

    seen: set[str] = set()
    for value in buckets:
        key = value.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        parsed = parse_publication_date(value, reference_time)
        if parsed.status == "parsed":
            return parsed

    return parse_publication_date("", reference_time)


__all__ = [
    "extract_publication_date",
    "parse_publication_date",
]
