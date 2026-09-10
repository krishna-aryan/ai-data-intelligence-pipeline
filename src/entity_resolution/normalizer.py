from __future__ import annotations

import re


LEGAL_SUFFIXES = (
    "inc",
    "inc.",
    "llc",
    "ltd",
    "ltd.",
    "limited",
    "corp",
    "corp.",
    "corporation",
    "co",
    "co.",
)


def normalize_name(name: str) -> str:
    if not isinstance(name, str):
        raise TypeError("name must be a string")

    value = name.strip().lower()
    value = re.sub(r"\s+", " ", value)
    value = value.replace("&", " and ")
    value = value.replace("+", " plus ")
    value = re.sub(r"[^a-z0-9\s]", " ", value)
    value = re.sub(r"\s+", " ", value).strip()

    for suffix in sorted(LEGAL_SUFFIXES, key=len, reverse=True):
        pattern = rf"\b{re.escape(suffix)}\b"
        value = re.sub(pattern, "", value)

    value = re.sub(r"\s+", " ", value).strip()
    value = value.replace("  ", " ")
    return value
