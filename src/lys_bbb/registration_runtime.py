"""Canonical cross-platform registration runtime contract."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


ANTSPYX_VERSION = "0.6.3"
ANTSPYX_ENGINE = "ANTsPyx"
ANTSPYX_BACKEND = "antspyx"


@dataclass(frozen=True)
class AntsExecutables:
    """Virtual identities for ANTsPyx compiled operations."""

    registration: Path
    apply_transforms: Path
    n4_bias_field_correction: Path
    create_jacobian: Path
    version: str = ANTSPYX_VERSION
    engine: str = ANTSPYX_ENGINE


@dataclass(frozen=True)
class CommandExecution:
    """Captured outcome of one process-isolated compiled operation."""

    args: tuple[str, ...]
    return_code: int
    stdout: str
    stderr: str
    runtime_seconds: float


class CommandRunner(Protocol):
    def __call__(self, args: tuple[str, ...], cwd: Path) -> CommandExecution: ...
