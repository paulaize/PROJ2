"""Frozen service for opening and migrating schema-v1 ``.lysbbb`` projects.

New studies use ``lys_bbb_app.services.StudyService`` and the schema-v6
``StudyRepository``. Keep this adapter only for backward compatibility and do not add
new application or scientific behavior here.
"""

from __future__ import annotations

from pathlib import Path

from lys_bbb.project_state import (
    PROJECT_FILE_SUFFIX,
    InputFolderKind,
    ProjectDatabase,
    ProjectSnapshot,
    ProjectStateError,
)


class ProjectService:
    """Manage one legacy single-file project for compatibility workflows."""

    def __init__(self) -> None:
        self._database: ProjectDatabase | None = None

    @property
    def current_project(self) -> ProjectSnapshot | None:
        if self._database is None:
            return None
        return self._database.snapshot()

    def create_project(
        self,
        database_path: Path | str,
        *,
        name: str | None = None,
    ) -> ProjectSnapshot:
        path = Path(database_path).expanduser()
        project_name = (name or _project_name_from_path(path)).strip()
        self._database = ProjectDatabase.create(path, name=project_name)
        return self._database.snapshot()

    def open_project(self, database_path: Path | str) -> ProjectSnapshot:
        self._database = ProjectDatabase.open(database_path)
        return self._database.snapshot()

    def close_project(self) -> None:
        self._database = None

    def set_input_folder(
        self,
        kind: InputFolderKind | str,
        folder: Path | str,
    ) -> ProjectSnapshot:
        if self._database is None:
            raise ProjectStateError("Create or open a project before selecting input folders.")
        return self._database.set_input_folder(kind, folder)


def _project_name_from_path(path: Path) -> str:
    name = path.name
    if name.lower().endswith(PROJECT_FILE_SUFFIX):
        name = name[: -len(PROJECT_FILE_SUFFIX)]
    return name or "Mouse MRI project"
