import json
import os
from pathlib import Path

import pytest

from src.integrations.google_sheets import GoogleSheetsAPIClient, GoogleSheetsExporter
from src.storage.repository import SQLiteRecordRepository


def _credentials_available() -> bool:
    value = os.getenv("GOOGLE_SHEETS_CREDENTIALS", "").strip()
    if not value:
        return False
    path = Path(value)
    if path.is_file():
        return True
    try:
        return isinstance(json.loads(value), dict)
    except (TypeError, ValueError):
        return False


@pytest.mark.live
@pytest.mark.skipif(
    not os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID", "").strip() or not _credentials_available(),
    reason="GOOGLE_SHEETS_SPREADSHEET_ID and GOOGLE_SHEETS_CREDENTIALS are required",
)
def test_live_google_sheets_minimal_empty_export(tmp_path):
    repository = SQLiteRecordRepository(tmp_path / "live-export.sqlite3")
    client = GoogleSheetsAPIClient.from_credentials(os.environ["GOOGLE_SHEETS_CREDENTIALS"])
    result = GoogleSheetsExporter(
        repository,
        client,
        spreadsheet_id=os.environ["GOOGLE_SHEETS_SPREADSHEET_ID"],
    ).export()

    assert result.total_rows == 0
    assert len(result.worksheets) == 6