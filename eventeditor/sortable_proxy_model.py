import typing

import PyQt5.QtCore as qc # type: ignore


class SortableHeaderProxyModel(qc.QSortFilterProxyModel):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._sort_descriptor_column: typing.Optional[int] = None
        self._sort_descriptor_text = ''

    def setSortDescriptor(self, column: int, text: str) -> None:
        previous_column = self._sort_descriptor_column
        self._sort_descriptor_column = column if column >= 0 and text else None
        self._sort_descriptor_text = text

        columns = [col for col in (previous_column, self._sort_descriptor_column) if col is not None]
        if columns:
            self.headerDataChanged.emit(qc.Qt.Horizontal, min(columns), max(columns))

    def headerData(self, section, orientation, role) -> qc.QVariant:
        value = super().headerData(section, orientation, role)
        if (
            role == qc.Qt.DisplayRole
            and orientation == qc.Qt.Horizontal
            and section == self._sort_descriptor_column
            and self._sort_descriptor_text
        ):
            return f'{value} ({self._sort_descriptor_text})'
        return value
