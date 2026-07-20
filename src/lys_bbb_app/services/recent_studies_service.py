"""Application service for launcher recent-study history."""

from __future__ import annotations

from pathlib import Path

from lys_bbb_app.domain.study import RecentStudy, StudySnapshot
from lys_bbb_app.infrastructure.recent_studies import RecentStudiesStore


class RecentStudiesService:
    """Expose recent-study preferences without coupling Qt widgets to storage."""

    def __init__(self, path: Path | None = None, *, maximum: int = 8) -> None:
        self._store = RecentStudiesStore(path, maximum=maximum)

    def list(self) -> tuple[RecentStudy, ...]:
        return self._store.list()

    def record(self, study: StudySnapshot) -> None:
        self._store.record(study)
