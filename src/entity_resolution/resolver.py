from __future__ import annotations

from typing import Any

from .models import EntityMappingLog, ResolutionResult
from .normalizer import normalize_name
from .seed_data import SEED_ENTITIES


class EntityResolver:
    """Deterministic entity canonicalization with seed-based resolution only."""

    def __init__(self, seed_entities: list[dict[str, Any]] | None = None) -> None:
        self.seed_entities = seed_entities or SEED_ENTITIES

    def resolve_startup(self, name: str, source_url: str | None = None) -> ResolutionResult:
        return self._resolve(name=name, source_url=source_url, entity_type="startup")

    def resolve_product(self, name: str, source_url: str | None = None) -> ResolutionResult:
        return self._resolve(name=name, source_url=source_url, entity_type="product")

    def _resolve(self, *, name: str, source_url: str | None, entity_type: str) -> ResolutionResult:
        original_name = str(name).strip()
        normalized_name = normalize_name(original_name)

        if not normalized_name:
            return ResolutionResult(
                original_name=original_name,
                normalized_name="",
                canonical_name=None,
                matched_seed=False,
                match_type="unresolved",
                status="unresolved",
                reason="Empty name after normalization.",
            )

        for entry in self.seed_entities:
            canonical_name = str(entry["canonical_name"])
            candidate_names = [canonical_name]
            for alias in entry.get("aliases", []) or []:
                candidate_names.append(str(alias))

            normalized_canonicals = {normalize_name(candidate) for candidate in candidate_names}
            if normalized_name in normalized_canonicals:
                if normalize_name(canonical_name) == normalized_name:
                    return ResolutionResult(
                        original_name=original_name,
                        normalized_name=normalized_name,
                        canonical_name=canonical_name,
                        matched_seed=True,
                        match_type="exact_canonical",
                        status="exact_canonical",
                        reason=f"Deterministic canonical-name match for {canonical_name}.",
                    )
                return ResolutionResult(
                    original_name=original_name,
                    normalized_name=normalized_name,
                    canonical_name=canonical_name,
                    matched_seed=True,
                    match_type="exact_alias",
                    status="exact_alias",
                    reason=f"Deterministic alias match for {canonical_name}.",
                )

        unresolved = ResolutionResult(
            original_name=original_name,
            normalized_name=normalized_name,
            canonical_name=None,
            matched_seed=False,
            match_type="unresolved",
            status="unresolved",
            reason="No deterministic canonical or alias match found in the reference seed list.",
        )
        if entity_type == "product":
            return unresolved
        return unresolved

    def build_mapping_log(self, result: ResolutionResult, source_url: str | None = None) -> EntityMappingLog:
        return EntityMappingLog(
            original_name=result.original_name,
            normalized_name=result.normalized_name,
            canonical_name=result.canonical_name,
            match_type=result.match_type,
            reason=result.reason,
            source_url=source_url,
        )


__all__ = ["EntityResolver"]
