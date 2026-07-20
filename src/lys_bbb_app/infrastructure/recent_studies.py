"""Small JSON store for application-level recent-study history."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from lys_bbb_app.domain.study import StudySnapshot


@dataclass(frozen=True)
class RecentStudy:
    name: str
    path: str
    last_opened: str


class RecentStudiesStore:
    """Persist a bounded list without coupling it to any study database."""

    def __init__(self, path: Path | None = None, *, maximum: int = 8) -> None:
        self.path = path or Path.home() / ".lys_bbb" / "recent_studies.json"
        self.maximum = maximum

    def list(self) -> tuple[RecentStudy, ...]:
        if not self.path.is_file():
            return ()
        try:
            payload = json.loads(self.path.read_text())
            records = payload.get("recent_studies", [])
            return tuple(
                RecentStudy(
                    name=str(record["name"]),
                    path=str(record["path"]),
                    last_opened=str(record["last_opened"]),
                )
                for record in records[: self.maximum]
            )
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            return ()

    def record(self, study: StudySnapshot) -> None:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        current = [
            entry
            for entry in self.list()
            if Path(entry.path).expanduser() != study.root_path
        ]
        entries = [
            RecentStudy(name=study.name, path=str(study.root_path), last_opened=now),
            *current,
        ][: self.maximum]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(
                {"recent_studies": [asdict(entry) for entry in entries]},
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        temporary.replace(self.path)
