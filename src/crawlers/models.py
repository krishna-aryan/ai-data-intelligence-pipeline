from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CrawlResult(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    requested_url: str
    status: int | None = None
    success: bool = False
    text: str = ""
    error: str | None = None
    error_type: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_success(self) -> bool:
        return self.success

    @property
    def is_error(self) -> bool:
        return not self.success


__all__ = ["CrawlResult"]
