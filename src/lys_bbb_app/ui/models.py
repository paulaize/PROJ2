"""Qt table models for subject and result design-preview data."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QSortFilterProxyModel,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QFont

from lys_bbb_app.domain.view_models import ResultViewModel, StatusValue, SubjectViewModel
from lys_bbb_app.ui.widgets import STATUS_COLOURS


SUBJECT_COLUMNS = (
    "Subject",
    "Animal ID",
    "Time",
    "Next action",
    "T1",
    "T2",
    "State",
)


class SubjectTableModel(QAbstractTableModel):
    longitudinal_edit_requested = Signal(str, str, str)

    def __init__(self, subjects: tuple[SubjectViewModel, ...] = ()) -> None:
        super().__init__()
        self.subjects = subjects

    def set_subjects(self, subjects: tuple[SubjectViewModel, ...]) -> None:
        self.beginResetModel()
        self.subjects = subjects
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.subjects)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(SUBJECT_COLUMNS)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid():
            return None
        subject = self.subjects[index.row()]
        values = (
            subject.label,
            subject.animal_identifier or "",
            subject.time_identifier or "",
            subject.next_action,
            subject.t1_workflow_status,
            subject.t2_workflow_status,
            subject.overall,
        )
        value = values[index.column()]
        if role in {Qt.DisplayRole, Qt.EditRole}:
            return value.label if isinstance(value, StatusValue) else value
        if isinstance(value, StatusValue):
            background, foreground, _border = STATUS_COLOURS.get(
                value.kind,
                STATUS_COLOURS["neutral"],
            )
            if role == Qt.BackgroundRole:
                return QColor(background)
            if role == Qt.ForegroundRole:
                return QColor(foreground)
            if role == Qt.ToolTipRole:
                return value.label
            if role == Qt.FontRole:
                font = QFont()
                font.setBold(True)
                font.setPointSize(9)
                return font
        if role == Qt.FontRole and index.column() == 0:
            font = QFont()
            font.setBold(True)
            return font
        if role == Qt.UserRole:
            return subject
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        flags = super().flags(index)
        if index.isValid() and index.column() in {1, 2}:
            flags |= Qt.ItemIsEditable
        return flags

    def setData(self, index: QModelIndex, value, role: int = Qt.EditRole) -> bool:  # noqa: N802
        if (
            role != Qt.EditRole
            or not index.isValid()
            or index.column() not in {1, 2}
        ):
            return False
        subject = self.subjects[index.row()]
        text = str(value).strip()
        updated = replace(
            subject,
            animal_identifier=(
                (text or None)
                if index.column() == 1
                else subject.animal_identifier
            ),
            time_identifier=(
                (text or None)
                if index.column() == 2
                else subject.time_identifier
            ),
        )
        if updated == subject:
            return False
        subjects = list(self.subjects)
        subjects[index.row()] = updated
        self.subjects = tuple(subjects)
        self.dataChanged.emit(index, index, [Qt.DisplayRole, Qt.EditRole])
        self.longitudinal_edit_requested.emit(
            updated.subject_id,
            updated.animal_identifier or "",
            updated.time_identifier or "",
        )
        return True

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):  # noqa: N802
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return SUBJECT_COLUMNS[section]
        return super().headerData(section, orientation, role)

    def subject_at(self, row: int) -> SubjectViewModel | None:
        return self.subjects[row] if 0 <= row < len(self.subjects) else None


class SubjectFilterProxyModel(QSortFilterProxyModel):
    def __init__(self) -> None:
        super().__init__()
        self.search_text = ""
        self.group_name = "All groups"
        self.state_name = "All states"
        self.setDynamicSortFilter(True)

    def set_filters(self, *, search: str, group: str, state: str) -> None:
        self.beginFilterChange()
        self.search_text = search.strip().lower()
        self.group_name = group
        self.state_name = state
        self.endFilterChange(QSortFilterProxyModel.Direction.Rows)

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:  # noqa: N802
        source = self.sourceModel()
        subject = source.subject_at(source_row) if isinstance(source, SubjectTableModel) else None
        if subject is None:
            return False
        searchable = " ".join(
            value
            for value in (
                subject.label,
                subject.animal_identifier,
                subject.time_identifier,
            )
            if value
        ).lower()
        if self.search_text and self.search_text not in searchable:
            return False
        if self.group_name != "All groups" and subject.group != self.group_name:
            return False
        if self.state_name != "All states":
            statuses = (
                subject.overall,
                subject.t1_data,
                subject.brain_mask,
                subject.registration,
                subject.t1_result,
                subject.t2_data,
                subject.t2_lesion,
            )
            matches = {
                "Needs validation": subject.needs_input_validation,
                "Needs review": any(status.kind == "review" for status in statuses),
                "Ready": subject.next_action.kind == "ready",
                "Processing": any(
                    status.kind == "processing" for status in statuses
                ),
                "Complete": subject.overall.kind == "approved",
                "Blocked": any(status.kind == "failed" for status in statuses),
            }
            if not matches.get(self.state_name, False):
                return False
        return True


RESULT_COLUMNS = (
    "Subject",
    "Animal ID",
    "Time",
    "Group",
    "T1 enhancement",
    "T2 lesion volume",
    "Method version",
)


class ResultsTableModel(QAbstractTableModel):
    def __init__(self, results: tuple[ResultViewModel, ...] = ()) -> None:
        super().__init__()
        self.results = results

    def set_results(self, results: tuple[ResultViewModel, ...]) -> None:
        self.beginResetModel()
        self.results = results
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.results)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(RESULT_COLUMNS)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid():
            return None
        result = self.results[index.row()]
        values = (
            result.subject_id,
            result.animal_identifier,
            result.time_identifier,
            result.group,
            result.t1_value,
            result.t2_value,
            result.method_version,
        )
        states = (None, None, None, None, result.t1_state, result.t2_state, None)
        if role == Qt.DisplayRole:
            if index.column() == 3 and values[index.column()] is None:
                return "Unassigned"
            return values[index.column()] or ""
        state = states[index.column()]
        if state is not None:
            background, foreground, _border = STATUS_COLOURS.get(
                state.kind,
                STATUS_COLOURS["neutral"],
            )
            if role == Qt.BackgroundRole:
                return QColor(background)
            if role == Qt.ForegroundRole:
                return QColor(foreground)
            if role == Qt.ToolTipRole:
                return state.label
        if role == Qt.FontRole and index.column() == 0:
            font = QFont()
            font.setBold(True)
            return font
        if role == Qt.UserRole:
            return result
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):  # noqa: N802
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return RESULT_COLUMNS[section]
        return super().headerData(section, orientation, role)


class ApprovedResultsProxyModel(QSortFilterProxyModel):
    def __init__(self) -> None:
        super().__init__()
        self.approved_only = False

    def set_approved_only(self, enabled: bool) -> None:
        self.beginFilterChange()
        self.approved_only = enabled
        self.endFilterChange(QSortFilterProxyModel.Direction.Rows)

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:  # noqa: N802
        if not self.approved_only:
            return True
        source = self.sourceModel()
        if not isinstance(source, ResultsTableModel):
            return True
        result = source.results[source_row]
        return any(
            state.kind == "approved"
            for state in (result.t1_state, result.t2_state)
        )
