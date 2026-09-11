from __future__ import annotations

import argparse
import asyncio
import sys

from src.demo import run_demo_sync
from src.live import run_live
from src.source_config import SourceConfigurationError


LIVE_MODE_MESSAGE = (
    "Live mode is not yet end-to-end wired. No source URL configuration or live "
    "workflow is defined; refusing to fall back to DEMO fixtures."
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.main",
        description="Run the GraphOne / FrontierAtlas AI Data Intelligence Pipeline.",
    )
    parser.add_argument(
        "--mode",
        choices=("offline-demo", "live"),
        required=True,
        help="offline-demo uses deterministic fixtures; live uses configured public source URLs and may require LLM credentials.",
    )
    return parser


def _print_demo_summary(result, exported_tabs: tuple[str, ...]) -> None:
    print("MODE: OFFLINE-DEMO (DEMO / TEST FIXTURES ONLY)")
    print("DEMO database: temporary SQLite database")
    print("AUDIT SUMMARY")
    for field in ("fetched", "extracted", "resolved", "unresolved", "persisted", "succeeded", "failed", "retried"):
        print(f"{field}: {getattr(result, field)}")
    print("QUEUE METRICS")
    for field in ("queued", "started", "succeeded", "failed", "retried", "skipped", "cancelled"):
        print(f"{field}: {getattr(result, field)}")
    print("EXPORTED TABS: " + ", ".join(exported_tabs))
    print("DEMO NOTE: fixture values are not production intelligence data.")


def _print_live_summary(run_result) -> None:
    print("MODE: LIVE (EXPLICIT PUBLIC SOURCE URLS; NO DEMO FALLBACK)")
    for source in run_result.source_results:
        detail = f" error={source.error}" if source.error else ""
        print(f"SOURCE {source.entity_type}: {source.status} records={source.record_count}{detail}")
    if run_result.skipped_sources:
        print("SKIPPED UNCONFIGURED: " + ", ".join(run_result.skipped_sources))
    print(f"FETCHED RECORDS: {run_result.fetched_records}")
    if run_result.messages:
        for message in run_result.messages:
            print(f"LIVE NOTE: {message}")
    if run_result.pipeline_result is not None:
        result = run_result.pipeline_result
        for field in ("extracted", "resolved", "unresolved", "persisted", "succeeded", "failed", "retried"):
            print(f"{field}: {getattr(result, field)}")
        print(
            "QUEUE METRICS: "
            + ", ".join(f"{field}={getattr(result, field)}" for field in ("queued", "started", "succeeded", "failed", "retried", "skipped", "cancelled"))
        )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.mode == "live":
            try:
                live_result = asyncio.run(run_live())
            except SourceConfigurationError as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 2
            _print_live_summary(live_result)
            if not live_result.extraction_available and live_result.fetched_records:
                return 2
            return 0
        result, exported_tabs, _database_path = run_demo_sync()
        _print_demo_summary(result, exported_tabs)
        return 0
    except Exception as exc:
        print(f"ERROR: pipeline execution failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_parser", "main"]