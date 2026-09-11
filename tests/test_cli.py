from __future__ import annotations

import os
import subprocess
import sys


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.pop("GEMINI_API_KEY", None)
    environment.pop("GROQ_API_KEY", None)
    environment.pop("CEREBRAS_API_KEY", None)
    environment.pop("GOOGLE_SHEETS_CREDENTIALS", None)
    environment.pop("GOOGLE_SHEETS_SPREADSHEET_ID", None)
    environment.pop("STARTUP_SOURCE_URL", None)
    environment.pop("PRODUCT_SOURCE_URL", None)
    environment.pop("RESEARCH_PAPER_SOURCE_URL", None)
    environment.pop("JOB_SOURCE_URL", None)
    environment.pop("NEWS_SOURCE_URL", None)
    return subprocess.run(
        [sys.executable, "-m", "src.main", *args],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )


def test_cli_help():
    completed = run_cli("--help")

    assert completed.returncode == 0
    assert "offline-demo" in completed.stdout
    assert "live" in completed.stdout
    assert "public source URLs" in completed.stdout


def test_offline_demo_completes_without_credentials_or_network():
    completed = run_cli("--mode", "offline-demo")

    assert completed.returncode == 0
    assert "MODE: OFFLINE-DEMO" in completed.stdout
    for stage in ("fetched", "extracted", "resolved", "unresolved", "persisted", "succeeded", "failed", "retried"):
        assert f"{stage}:" in completed.stdout
    assert "Startups" in completed.stdout
    assert "Entity Mapping Log" in completed.stdout


def test_live_mode_fails_without_falling_back_to_demo():
    completed = run_cli("--mode", "live")

    assert completed.returncode != 0
    assert "No live source URLs configured" in completed.stderr
    assert "OFFLINE-DEMO" not in completed.stdout