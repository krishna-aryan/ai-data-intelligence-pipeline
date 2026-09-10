from datetime import datetime, timedelta, timezone

import pytest

from src.freshness import (
    DateParseResult,
    FreshnessResult,
    evaluate_freshness,
    extract_publication_date,
    parse_publication_date,
)


REFERENCE = datetime(2026, 1, 10, 12, 0, tzinfo=timezone.utc)


def test_parse_iso8601_utc():
    result = parse_publication_date("2026-01-10T10:00:00Z", REFERENCE)
    assert result.status == "parsed"
    assert result.normalized_datetime == datetime(2026, 1, 10, 10, 0, tzinfo=timezone.utc)


def test_parse_iso8601_with_offset():
    result = parse_publication_date("2026-01-10T13:00:00+02:00", REFERENCE)
    assert result.status == "parsed"
    assert result.normalized_datetime == datetime(2026, 1, 10, 11, 0, tzinfo=timezone.utc)


def test_parse_rfc_date():
    result = parse_publication_date("Fri, 10 Jan 2026 11:00:00 GMT", REFERENCE)
    assert result.status == "parsed"
    assert result.normalized_datetime == datetime(2026, 1, 10, 11, 0, tzinfo=timezone.utc)


def test_parse_common_date_string():
    result = parse_publication_date("Jan 10, 2026", REFERENCE)
    assert result.status == "parsed"
    assert result.normalized_datetime == datetime(2026, 1, 10, 0, 0, tzinfo=timezone.utc)


def test_parse_relative_hours_ago():
    result = parse_publication_date("2 hours ago", REFERENCE)
    assert result.status == "parsed"
    assert result.normalized_datetime == datetime(2026, 1, 10, 10, 0, tzinfo=timezone.utc)


def test_parse_relative_minutes_ago():
    result = parse_publication_date("30 minutes ago", REFERENCE)
    assert result.status == "parsed"
    assert result.normalized_datetime == datetime(2026, 1, 10, 11, 30, tzinfo=timezone.utc)


def test_parse_relative_mins_ago():
    result = parse_publication_date("15 mins ago", REFERENCE)
    assert result.status == "parsed"
    assert result.normalized_datetime == datetime(2026, 1, 10, 11, 45, tzinfo=timezone.utc)


def test_parse_relative_days_ago():
    result = parse_publication_date("1 day ago", REFERENCE)
    assert result.status == "parsed"
    assert result.normalized_datetime == datetime(2026, 1, 9, 12, 0, tzinfo=timezone.utc)


def test_parse_yesterday():
    result = parse_publication_date("yesterday", REFERENCE)
    assert result.status == "parsed"
    assert result.normalized_datetime == datetime(2026, 1, 9, 12, 0, tzinfo=timezone.utc)


def test_missing_value_returns_missing_status():
    result = parse_publication_date(None, REFERENCE)
    assert result.status == "missing"
    assert result.normalized_datetime is None


def test_empty_value_returns_missing_status():
    result = parse_publication_date("   ", REFERENCE)
    assert result.status == "missing"


def test_malformed_value_returns_unparseable_status():
    result = parse_publication_date("not a date at all", REFERENCE)
    assert result.status == "unparseable"


def test_future_timestamp_is_identified_as_future():
    publication = datetime(2026, 1, 10, 13, 0, tzinfo=timezone.utc)
    result = evaluate_freshness(publication, REFERENCE)
    assert result.status == "future"


def test_exact_24_hour_boundary_is_fresh():
    publication = datetime(2026, 1, 9, 12, 0, tzinfo=timezone.utc)
    result = evaluate_freshness(publication, REFERENCE)
    assert result.status == "fresh"
    assert result.age_seconds == 86400


def test_just_over_24_hours_is_stale():
    publication = datetime(2026, 1, 9, 11, 59, 59, tzinfo=timezone.utc)
    result = evaluate_freshness(publication, REFERENCE)
    assert result.status == "stale"
    assert result.age_seconds == 86401


def test_timezone_aware_comparison():
    publication = datetime(2026, 1, 10, 10, 0, tzinfo=timezone.utc)
    result = evaluate_freshness(publication, REFERENCE)
    assert result.status == "fresh"


def test_naive_datetime_assumes_utc():
    naive = datetime(2026, 1, 10, 10, 0)
    result = parse_publication_date(naive, REFERENCE)
    assert result.status == "parsed"
    assert result.normalized_datetime.tzinfo is not None
    assert result.timezone_assumption == "naive datetime assumed UTC"


def test_reference_time_is_explicitly_used_for_parsing():
    reference = datetime(2026, 1, 10, 15, 0, tzinfo=timezone.utc)
    result = parse_publication_date("2 hours ago", reference)
    assert result.normalized_datetime == datetime(2026, 1, 10, 13, 0, tzinfo=timezone.utc)


def test_repeated_parse_is_deterministic():
    first = parse_publication_date("yesterday", REFERENCE)
    second = parse_publication_date("yesterday", REFERENCE)
    assert first.model_dump() == second.model_dump()


def test_extract_jsonld_date_published():
    source = '''
    <html><head>
    <script type="application/ld+json">{"datePublished": "2026-01-10T11:00:00Z"}</script>
    </head></html>
    '''
    result = extract_publication_date(source, REFERENCE)
    assert result.status == "parsed"
    assert result.normalized_datetime == datetime(2026, 1, 10, 11, 0, tzinfo=timezone.utc)


def test_extract_article_published_meta():
    source = '<html><head><meta property="article:published_time" content="2026-01-10T09:30:00-05:00"></head></html>'
    result = extract_publication_date(source, REFERENCE)
    assert result.status == "parsed"
    assert result.normalized_datetime == datetime(2026, 1, 10, 14, 30, tzinfo=timezone.utc)


def test_extract_date_meta():
    source = '<html><head><meta name="date" content="2026-01-10"></head></html>'
    result = extract_publication_date(source, REFERENCE)
    assert result.status == "parsed"
    assert result.normalized_datetime == datetime(2026, 1, 10, 0, 0, tzinfo=timezone.utc)


def test_extract_time_datetime_tag():
    source = '<html><body><time datetime="2026-01-10T08:00:00Z">Jan 10</time></body></html>'
    result = extract_publication_date(source, REFERENCE)
    assert result.status == "parsed"
    assert result.normalized_datetime == datetime(2026, 1, 10, 8, 0, tzinfo=timezone.utc)


def test_visible_date_fallback_is_used_when_no_meta_present():
    source = '<html><body>Published on Jan 9, 2026</body></html>'
    result = extract_publication_date(source, REFERENCE)
    assert result.status == "parsed"
    assert result.normalized_datetime == datetime(2026, 1, 9, 0, 0, tzinfo=timezone.utc)


def test_precedence_uses_higher_priority_valid_source():
    source = '''
    <html><head>
    <meta property="article:published_time" content="2026-01-10T09:00:00Z">
    <meta name="date" content="2026-01-08">
    </head></html>
    '''
    result = extract_publication_date(source, REFERENCE)
    assert result.normalized_datetime == datetime(2026, 1, 10, 9, 0, tzinfo=timezone.utc)


def test_invalid_high_priority_source_falls_through_to_next_valid_value():
    source = '''
    <html><head>
    <meta property="article:published_time" content="not-a-date">
    <meta name="date" content="2026-01-08">
    </head></html>
    '''
    result = extract_publication_date(source, REFERENCE)
    assert result.normalized_datetime == datetime(2026, 1, 8, 0, 0, tzinfo=timezone.utc)


def test_unknown_dates_stay_unknown():
    result = evaluate_freshness(None, REFERENCE)
    assert result.status == "unknown"


def test_custom_freshness_window_is_respected():
    publication = datetime(2026, 1, 9, 12, 0, tzinfo=timezone.utc)
    result = evaluate_freshness(publication, REFERENCE, max_age_hours=12)
    assert result.status == "stale"


def test_parse_result_has_useful_reason_fields():
    result = parse_publication_date("2 hours ago", REFERENCE)
    assert result.reason
    assert result.parsing_method


def test_freshness_result_model_types():
    result = evaluate_freshness(datetime(2026, 1, 9, 12, 0, tzinfo=timezone.utc), REFERENCE)
    assert isinstance(result, FreshnessResult)
    assert result.max_age_hours == 24


def test_no_network_requests_are_required_for_html_extraction():
    source = '<html><body>Published on Jan 9, 2026</body></html>'
    result = extract_publication_date(source, REFERENCE)
    assert result.status == "parsed"
