import re
import typing

import PyQt5.QtCore as qc  # type: ignore
import PyQt5.QtWidgets as q  # type: ignore


def four_digit_choice_label_entries(
        messages: typing.Mapping[str, str]) -> typing.List[typing.Tuple[str, str]]:
    entries = [
        (str(label), str(contents))
        for label, contents in messages.items()
        if re.fullmatch(r'\d{4}', str(label))
    ]
    return sorted(entries, key=lambda entry: int(entry[0]))


class ChoiceLabelPickerDialog(q.QDialog):
    def __init__(self, parent, entries: typing.Iterable[typing.Tuple[str, str]]) -> None:
        super().__init__(
            parent,
            qc.Qt.WindowTitleHint | qc.Qt.WindowSystemMenuHint | qc.Qt.WindowCloseButtonHint,
        )
        self.setWindowTitle('Pick from existing ChoiceLabels')
        self.resize(720, 480)

        self.table = q.QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(['Label', 'Contents'])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(q.QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(q.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(q.QAbstractItemView.SingleSelection)

        rows = list(entries)
        self.table.setRowCount(len(rows))
        for row, (label, contents) in enumerate(rows):
            self.table.setItem(row, 0, q.QTableWidgetItem(label))
            self.table.setItem(row, 1, q.QTableWidgetItem(contents))
        self.table.horizontalHeader().setSectionResizeMode(0, q.QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, q.QHeaderView.Stretch)
        self.table.setSortingEnabled(True)
        self.table.sortItems(0, qc.Qt.AscendingOrder)
        self.table.resizeRowsToContents()

        self.button_box = q.QDialogButtonBox(q.QDialogButtonBox.Ok | q.QDialogButtonBox.Cancel)
        self.ok_button = self.button_box.button(q.QDialogButtonBox.Ok)
        self.ok_button.setEnabled(False)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        self.table.itemSelectionChanged.connect(self._updateOkButton)
        self.table.cellDoubleClicked.connect(self._acceptRow)

        layout = q.QVBoxLayout(self)
        layout.addWidget(self.table, stretch=1)
        layout.addWidget(self.button_box)

    def _updateOkButton(self) -> None:
        self.ok_button.setEnabled(bool(self.table.selectionModel().selectedRows()))

    def _acceptRow(self, row: int, column: int) -> None:
        self.table.selectRow(row)
        self.accept()

    def selectedLabel(self) -> typing.Optional[str]:
        selected = self.table.selectionModel().selectedRows()
        if not selected:
            return None
        item = self.table.item(selected[0].row(), 0)
        return item.text() if item else None

    def accept(self) -> None:
        if self.selectedLabel() is None:
            return
        super().accept()
