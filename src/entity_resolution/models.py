from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ResolutionResult(BaseModel):
    original_name: str
    normalized_name: str
    canonical_name: str | None = None
    matched_seed: bool = False
    match_type: Literal["exact_canonical", "exact_alias", "unresolved"] = "unresolved"
    status: Literal["exact_canonical", "exact_alias", "unresolved"] = "unresolved"
    reason: str = ""


class EntityMappingLog(BaseModel):
    original_name: str
    normalized_name: str
    canonical_name: str | None = None
    match_type: Literal["exact_canonical", "exact_alias", "unresolved"] = "unresolved"
    reason: str = ""
    source_url: str | None = None


__all__ = ["EntityMappingLog", "ResolutionResult"]
