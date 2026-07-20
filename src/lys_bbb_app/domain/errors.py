"""Application-level errors shared across service and adapter boundaries."""

from __future__ import annotations


class StudyStateError(RuntimeError):
    """Raised when a requested study operation cannot be completed safely."""
