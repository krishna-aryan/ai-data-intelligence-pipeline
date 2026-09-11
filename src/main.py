from __future__ import annotations

import argparse
import sys

from src.demo import run_demo_sync


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
        help="offline-demo runs deterministic fixtures; live requires future source wiring.",
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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.mode == "live":
            print(f"ERROR: {LIVE_MODE_MESSAGE}", file=sys.stderr)
            return 2
        result, exported_tabs, _database_path = run_demo_sync()
        _print_demo_summary(result, exported_tabs)
        return 0
    except Exception as exc:
        print(f"ERROR: pipeline execution failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_parser", "main"]