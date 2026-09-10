from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .models import FreshnessResult


def _coerce_datetime(value: Any, *, name: str = "datetime") -> datetime:
    if value is None:
        raise ValueError(f"{name} cannot be None")
    if isinstance(value, datetime):
        dt = value
    else:
        raise TypeError(f"{name} must be a datetime instance")

    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def evaluate_freshness(
    publication_datetime: Any,
    reference_time: Any,
    max_age_hours: float = 24,
) -> FreshnessResult:
    reference_dt = _coerce_datetime(reference_time, name="reference_time")

    if publication_datetime is None:
        return FreshnessResult(
            publication_datetime=None,
            reference_datetime=reference_dt,
            age_seconds=None,
            max_age_hours=max_age_hours,
            status="unknown",
            reason="No publication datetime was supplied.",
        )

    try:
        publication_dt = _coerce_datetime(publication_datetime, name="publication_datetime")
    except (TypeError, ValueError):
        return FreshnessResult(
            publication_datetime=None,
            reference_datetime=reference_dt,
            age_seconds=None,
            max_age_hours=max_age_hours,
            status="unknown",
            reason="Publication datetime was not parseable or was not a datetime value.",
        )

    if publication_dt > reference_dt:
        return FreshnessResult(
            publication_datetime=publication_dt,
            reference_datetime=reference_dt,
            age_seconds=int((publication_dt - reference_dt).total_seconds()),
            max_age_hours=max_age_hours,
            status="future",
            reason="Publication date is in the future relative to the supplied reference time.",
        )

    age_seconds = int((reference_dt - publication_dt).total_seconds())
    max_age_seconds = max_age_hours * 3600

    if age_seconds <= max_age_seconds:
        return FreshnessResult(
            publication_datetime=publication_dt,
            reference_datetime=reference_dt,
            age_seconds=age_seconds,
            max_age_hours=max_age_hours,
            status="fresh",
            reason="Publication age is within the allowed freshness window.",
        )

    return FreshnessResult(
        publication_datetime=publication_dt,
        reference_datetime=reference_dt,
        age_seconds=age_seconds,
        max_age_hours=max_age_hours,
        status="stale",
        reason="Publication age exceeds the allowed freshness window.",
    )


__all__ = ["evaluate_freshness"]
