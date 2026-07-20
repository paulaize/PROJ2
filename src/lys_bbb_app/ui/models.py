"""Qt table models for subject and result design-preview data."""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QColor, QFont

from lys_bbb_app.domain.view_models import ResultViewModel, StatusValue, SubjectViewModel
from lys_bbb_app.ui.widgets import STATUS_COLOURS


SUBJECT_COLUMNS = (
    "Subject ID",
    "Group",
    "T1 data",
    "Brain mask",
    "Registration",
    "T1 result",
    "T2 data",
    "T2 lesion",
    "Overall",
    "Updated",
)


class SubjectTableModel(QAbstractTableModel):
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
            subject.group,
            subject.t1_data,
            subject.brain_mask,
            subject.registration,
            subject.t1_result,
            subject.t2_data,
            subject.t2_lesion,
            subject.overall,
            subject.updated,
        )
        value = values[index.column()]
        if role == Qt.DisplayRole:
            if index.column() == 1 and value is None:
                return "Unassigned"
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
        if self.search_text and self.search_text not in subject.label.lower():
            return False
        if self.group_name != "All groups" and subject.group != self.group_name:
            return False
        if self.state_name != "All states":
            state = self.state_name.lower()
            labels = {
                subject.overall.label.lower(),
                subject.t1_data.label.lower(),
                subject.brain_mask.label.lower(),
                subject.registration.label.lower(),
                subject.t1_result.label.lower(),
                subject.t2_data.label.lower(),
                subject.t2_lesion.label.lower(),
            }
            if state not in labels:
                return False
        return True


RESULT_COLUMNS = (
    "Subject",
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
            result.group,
            result.t1_value,
            result.t2_value,
            result.method_version,
        )
        states = (None, None, result.t1_state, result.t2_state, None)
        if role == Qt.DisplayRole:
            if index.column() == 1 and values[index.column()] is None:
                return "Unassigned"
            return values[index.column()]
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
