"""Conservative discovery and normalization of longitudinal subject identifiers."""

from __future__ import annotations

import re


HOUR_TIMEPOINTS = (0, 1, 2, 3, 6, 12, 24, 48, 120, 168)
DAY_TIMEPOINTS = (1, 2, 5, 7, 14, 28, 30, 31)
CANONICAL_TIME_IDENTIFIERS = (
    *(f"{value}H" for value in HOUR_TIMEPOINTS),
    *(f"D{value}" for value in DAY_TIMEPOINTS),
)

_ANIMAL = re.compile(r"C\d+S\d+", re.IGNORECASE)
_BD_ANIMAL = re.compile(r"BD[_-]\d+(?:[_-]\d+)?", re.IGNORECASE)
_TIME_TOKEN = re.compile(
    r"(?<![A-Za-z0-9])(?:"
    r"(?P<letter_first>[HDJ])_?(?P<number_after>\d+)"
    r"|(?P<number_first>\d+)_?(?P<letter_after>[HDJ])"
    r")(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_TIME_VALUE = re.compile(
    r"^(?:(?P<letter_first>[HDJ])_?(?P<number_after>\d+)"
    r"|(?P<number_first>\d+)_?(?P<letter_after>[HDJ]))$",
    re.IGNORECASE,
)


def normalize_time_identifier(value: str | None) -> str | None:
    """Return a canonical grouping label or fail for an unsupported value."""

    text = (value or "").strip()
    if not text:
        return None
    match = _TIME_VALUE.fullmatch(text)
    if match is None:
        raise ValueError(
            "Use a supported longitudinal time identifier such as 1H, D7, or J14."
        )
    canonical = _canonical_time_match(match)
    if canonical not in CANONICAL_TIME_IDENTIFIERS:
        raise ValueError(f"Unsupported longitudinal time identifier: {value}")
    return canonical


def infer_longitudinal_identifiers(name: str) -> tuple[str | None, str | None]:
    """Infer known animal and time identifiers, leaving uncertain values empty."""

    animal_match = _ANIMAL.search(name)
    if animal_match is not None:
        animal_identifier = animal_match.group(0).upper()
    else:
        bd_match = _BD_ANIMAL.search(name)
        animal_identifier = (
            re.sub(r"-", "_", bd_match.group(0).upper())
            if bd_match is not None
            else None
        )

    candidates = {
        canonical
        for match in _TIME_TOKEN.finditer(name)
        if (canonical := _canonical_time_match(match))
        in CANONICAL_TIME_IDENTIFIERS
    }
    time_identifier = next(iter(candidates)) if len(candidates) == 1 else None
    return animal_identifier, time_identifier


def _canonical_time_match(match: re.Match[str]) -> str:
    letter = match.group("letter_first") or match.group("letter_after")
    number = int(match.group("number_after") or match.group("number_first"))
    return f"{number}H" if letter.casefold() == "h" else f"D{number}"


__all__ = [
    "CANONICAL_TIME_IDENTIFIERS",
    "DAY_TIMEPOINTS",
    "HOUR_TIMEPOINTS",
    "infer_longitudinal_identifiers",
    "normalize_time_identifier",
]
