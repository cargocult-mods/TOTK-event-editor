import typing

from eventeditor.event_library import (
    EVENT_LIBRARY_QUERY,
    EventLibraryEntry,
    EventLibraryExample,
    EventLibraryResult,
    MAX_ENTRY_EXAMPLES,
    SOURCE_GROUP_CURRENT,
    SOURCE_GROUP_MOD,
    SOURCE_GROUP_VANILLA,
    format_library_value,
    source_group_title,
)
import PyQt5.QtCore as qc # type: ignore
import PyQt5.QtWidgets as q # type: ignore


class EventLibraryDialog(q.QDialog):
    goToExampleRequested = qc.pyqtSignal(object)

    def __init__(self,
                 parent,
                 actor_name: str,
                 kind: str,
                 result: EventLibraryResult) -> None:
        super().__init__(parent, qc.Qt.WindowTitleHint | qc.Qt.WindowSystemMenuHint | qc.Qt.WindowCloseButtonHint)
        self.setWindowTitle('Event library')
        self.resize(980, 560)
        self.actor_name = actor_name
        self.kind = kind
        self.result = result
        self.mod_context_enabled = getattr(result, 'mod_context_enabled', True)
        self._selected_entry = None  # type: typing.Optional[EventLibraryEntry]
        self._rebuild_requested = False
        self._show_all_uses = False

        layout = q.QVBoxLayout(self)
        header = q.QLabel('{} {} library'.format(actor_name, 'query' if kind == EVENT_LIBRARY_QUERY else 'action'))
        header.setStyleSheet('font-weight: bold;')
        layout.addWidget(header)

        self.search_edit = q.QLineEdit()
        self.search_edit.setPlaceholderText('Search')
        self.search_edit.textChanged.connect(self.filterRows)
        layout.addWidget(self.search_edit)

        splitter = q.QSplitter(qc.Qt.Horizontal)
        self.tree = q.QTreeWidget()
        self.tree.setColumnCount(7)
        self.tree.setHeaderLabels(['Node type', 'Params', 'Examples', 'Cases', 'File', 'Mod', 'Vanilla'])
        for column in range(self.tree.columnCount()):
            self.tree.headerItem().setToolTip(column, self.tree.headerItem().text(column))
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setHorizontalScrollBarPolicy(qc.Qt.ScrollBarAlwaysOff)
        self.tree.setTextElideMode(qc.Qt.ElideRight)
        self.tree.setSelectionMode(q.QAbstractItemView.SingleSelection)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setMinimumSectionSize(24)
        self.tree.header().setSectionResizeMode(0, q.QHeaderView.Stretch)
        for column in range(1, self.tree.columnCount()):
            self.tree.header().setSectionResizeMode(column, q.QHeaderView.Fixed)
        self.tree.setColumnHidden(5, not self.mod_context_enabled)
        self.tree.currentItemChanged.connect(self.onCurrentItemChanged)
        self.tree.itemDoubleClicked.connect(lambda item, column: self.accept() if self._selected_entry else None)
        splitter.addWidget(self.tree)

        splitter.addWidget(self.createDetailsPane())
        splitter.setSizes([460, 520])
        layout.addWidget(splitter, stretch=1)

        if result.errors:
            error_row = q.QHBoxLayout()
            error_label = q.QLabel(
                '{} files were skipped while collecting example values.'.format(len(result.errors))
            )
            error_label.setToolTip(
                'Details lists the file and parser/decompression reason for each skip.'
            )
            error_row.addWidget(error_label)
            error_details = q.QPushButton('Details...')
            error_details.clicked.connect(self.showSkippedFiles)
            error_row.addWidget(error_details)
            error_row.addStretch(1)
            layout.addLayout(error_row)

        self.button_box = q.QDialogButtonBox(q.QDialogButtonBox.Cancel)
        self.rebuild_button = self.button_box.addButton('Rebuild Library', q.QDialogButtonBox.ActionRole)
        self.rebuild_button.clicked.connect(self.requestRebuild)
        self.add_button = self.button_box.addButton('Add to Actor', q.QDialogButtonBox.AcceptRole)
        self.add_button.setEnabled(False)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        self.populate()

    def populate(self) -> None:
        for entry in self.result.entries:
            item = q.QTreeWidgetItem([
                entry.name,
                str(len(entry.parameters)),
                entry.example_count_label(),
                str(entry.case_count()) if entry.case_count() else '',
                'Y' if entry.has_current_file_source() else '',
                'Y' if entry.has_mod_source() else '',
                'Y' if entry.has_vanilla_source() else '',
            ])
            item.setData(0, qc.Qt.UserRole, entry)
            item.setToolTip(0, entry.name)
            item.setToolTip(1, self.parameterTooltip(entry))
            item.setToolTip(2, self.exampleTooltip(entry))
            if entry.case_count():
                item.setToolTip(3, 'Observed switch case values: {}'.format(entry.case_value_summary()))
            else:
                item.setToolTip(3, 'No observed switch cases')
            item.setToolTip(4, 'Current open file' if entry.has_current_file_source() else 'Not seen in current open file')
            item.setToolTip(5, 'Mod actor file or mod flow examples' if entry.has_mod_source() else 'Not seen in the mod actor file or mod flow examples')
            item.setToolTip(6, 'Vanilla actor file or vanilla flow examples' if entry.has_vanilla_source() else 'Not seen in vanilla sources')
            for column in range(1, self.tree.columnCount()):
                item.setTextAlignment(column, qc.Qt.AlignCenter)
            self.tree.addTopLevelItem(item)

        self.fitCompactTreeColumns()
        if self.tree.topLevelItemCount():
            self.tree.setCurrentItem(self.tree.topLevelItem(0))

    def parameterTooltip(self, entry: EventLibraryEntry) -> str:
        if not entry.parameters:
            return '(none known)'
        return '\n'.join(
            '{}: {}'.format(parameter.name, parameter.type_label())
            for parameter in entry.parameters
        )

    def exampleTooltip(self, entry: EventLibraryEntry) -> str:
        observed_count = entry.observed_example_count()
        if not observed_count:
            return 'No observed example uses'
        if observed_count > len(entry.preview_examples()):
            return '{} observed uses; preview shows up to {} samples'.format(observed_count, MAX_ENTRY_EXAMPLES)
        return '{} observed example use{}'.format(observed_count, '' if observed_count == 1 else 's')

    def fitCompactTreeColumns(self) -> None:
        metrics = self.tree.fontMetrics()
        for column in range(1, self.tree.columnCount()):
            widest = 0
            for row in range(self.tree.topLevelItemCount()):
                widest = max(widest, metrics.horizontalAdvance(self.tree.topLevelItem(row).text(column)))
            self.tree.setColumnWidth(column, max(24, widest + 22))

    def createDetailsPane(self) -> q.QWidget:
        pane = q.QWidget()
        layout = q.QVBoxLayout(pane)
        self.detail_layout = layout
        layout.setContentsMargins(8, 0, 0, 0)
        layout.setSpacing(8)

        self.detail_title = q.QLabel()
        self.detail_title.setStyleSheet('font-weight: bold;')
        self.detail_title.setTextInteractionFlags(qc.Qt.TextSelectableByMouse)
        self.detail_title.setSizePolicy(q.QSizePolicy.Expanding, q.QSizePolicy.Maximum)
        layout.addWidget(self.detail_title)

        self.source_label = q.QLabel()
        self.source_label.setWordWrap(True)
        self.source_label.setTextInteractionFlags(qc.Qt.TextSelectableByMouse)
        self.source_label.setSizePolicy(q.QSizePolicy.Expanding, q.QSizePolicy.Maximum)
        layout.addWidget(self.source_label)

        self.parameter_table = q.QTableWidget()
        self.parameter_table.setColumnCount(3)
        self.parameter_table.setHorizontalHeaderLabels(['Type', 'Key', 'Value'])
        self.parameter_table.verticalHeader().hide()
        self.parameter_table.setEditTriggers(q.QAbstractItemView.NoEditTriggers)
        self.parameter_table.setSelectionBehavior(q.QAbstractItemView.SelectRows)
        self.parameter_table.setSelectionMode(q.QAbstractItemView.SingleSelection)
        self.parameter_table.setAlternatingRowColors(True)
        self.parameter_table.horizontalHeader().setSectionResizeMode(q.QHeaderView.ResizeToContents)
        self.parameter_table.horizontalHeader().setSectionResizeMode(2, q.QHeaderView.Stretch)
        self.parameter_table.setSizePolicy(q.QSizePolicy.Expanding, q.QSizePolicy.Fixed)
        layout.addWidget(self.parameter_table)

        self.no_params_label = q.QLabel('No known parameters.')
        self.no_params_label.setAlignment(qc.Qt.AlignLeft)
        self.no_params_label.setFrameShape(q.QFrame.StyledPanel)
        self.no_params_label.setMargin(8)
        self.no_params_label.setSizePolicy(q.QSizePolicy.Expanding, q.QSizePolicy.Fixed)
        layout.addWidget(self.no_params_label)

        self.case_label = q.QLabel()
        self.case_label.setStyleSheet('font-weight: bold;')
        layout.addWidget(self.case_label)
        self.case_values = q.QLineEdit()
        self.case_values.setReadOnly(True)
        self.case_values.setFocusPolicy(qc.Qt.NoFocus)
        layout.addWidget(self.case_values)

        examples_header = q.QHBoxLayout()
        self.examples_label = q.QLabel('Observed examples')
        self.examples_label.setStyleSheet('font-weight: bold;')
        examples_header.addWidget(self.examples_label)
        examples_header.addStretch(1)
        self.preview_button = q.QPushButton('Preview')
        self.preview_button.clicked.connect(lambda checked=False: self.setExampleMode(False))
        examples_header.addWidget(self.preview_button)
        self.all_uses_button = q.QPushButton('All Uses...')
        self.all_uses_button.clicked.connect(lambda checked=False: self.setExampleMode(True))
        examples_header.addWidget(self.all_uses_button)
        layout.addLayout(examples_header)

        self.example_filter_widget = q.QWidget()
        filter_layout = q.QHBoxLayout(self.example_filter_widget)
        filter_layout.setContentsMargins(0, 0, 0, 0)
        self.current_examples_check = q.QCheckBox('Current')
        self.mod_examples_check = q.QCheckBox('Mod')
        self.vanilla_examples_check = q.QCheckBox('Vanilla')
        self.mod_examples_check.setVisible(self.mod_context_enabled)
        for checkbox in (self.current_examples_check, self.mod_examples_check, self.vanilla_examples_check):
            checkbox.setChecked(True)
            checkbox.toggled.connect(self.onExampleFiltersChanged)
            filter_layout.addWidget(checkbox)
        filter_layout.addStretch(1)
        layout.addWidget(self.example_filter_widget)

        self.example_search_edit = q.QLineEdit()
        self.example_search_edit.setPlaceholderText('Search uses')
        self.example_search_edit.textChanged.connect(self.onExampleFiltersChanged)
        layout.addWidget(self.example_search_edit)

        self.unusual_only_check = q.QCheckBox('Unusual only')
        self.unusual_only_check.setToolTip(
            'Shows uses with parameter or switch-case patterns that are uncommon among the observed examples.'
        )
        self.unusual_only_check.toggled.connect(self.onExampleFiltersChanged)
        layout.addWidget(self.unusual_only_check)

        self.examples_list = q.QListWidget()
        self.examples_list.setSelectionMode(q.QAbstractItemView.SingleSelection)
        self.examples_list.setContextMenuPolicy(qc.Qt.CustomContextMenu)
        self.examples_list.customContextMenuRequested.connect(self.onExamplesContextMenu)
        layout.addWidget(self.examples_list, stretch=1)
        self.details_bottom_spacer = q.QSpacerItem(0, 0, q.QSizePolicy.Minimum, q.QSizePolicy.Expanding)
        layout.addItem(self.details_bottom_spacer)
        return pane

    def selectedEntry(self) -> typing.Optional[EventLibraryEntry]:
        return self._selected_entry

    def rebuildRequested(self) -> bool:
        return self._rebuild_requested

    def requestRebuild(self) -> None:
        self._rebuild_requested = True
        self.reject()

    def onCurrentItemChanged(self, current, previous) -> None:
        entry = current.data(0, qc.Qt.UserRole) if current else None
        self._selected_entry = entry if isinstance(entry, EventLibraryEntry) else None
        self.add_button.setEnabled(self._selected_entry is not None)
        self.setDetails(self._selected_entry)

    def setDetails(self, entry: typing.Optional[EventLibraryEntry]) -> None:
        self.detail_title.setText(entry.name if entry else '')
        self.source_label.setText('Found in: {}'.format(entry.source_summary()) if entry else '')
        self.populateParameterTable(entry)
        self.populateCaseTable(entry)
        self.populateExamples(entry)

    def _readonlyItem(self, text: str) -> q.QTableWidgetItem:
        item = q.QTableWidgetItem(text)
        item.setFlags(item.flags() & ~qc.Qt.ItemIsEditable)
        return item

    def _fitTableToRows(self, table: q.QTableWidget, row_count: int, max_visible_rows: int = 6) -> None:
        if row_count <= 0:
            return
        visible_rows = min(row_count, max_visible_rows)
        row_height = table.verticalHeader().defaultSectionSize()
        header_height = table.horizontalHeader().height()
        frame = table.frameWidth() * 2
        height = header_height + (visible_rows * row_height) + frame + 6
        table.setMinimumHeight(height)
        table.setMaximumHeight(height)

    def populateParameterTable(self, entry: typing.Optional[EventLibraryEntry]) -> None:
        parameters = entry.parameters if entry else []
        self.parameter_table.setVisible(bool(parameters))
        self.no_params_label.setVisible(not bool(parameters))
        if not parameters:
            has_other_details = bool(entry and (entry.case_count() or entry.observed_example_count()))
            self.no_params_label.setText('No known parameters.' if has_other_details else 'No known parameters or examples.')
        self.parameter_table.setRowCount(len(parameters))
        for row, parameter in enumerate(parameters):
            type_item = self._readonlyItem(parameter.type_label())
            key_item = self._readonlyItem(parameter.name)
            value = parameter.seed_value()
            value_item = self._readonlyItem('' if value is None else format_library_value(value, quote_strings=False))
            if value is not None:
                font = value_item.font()
                font.setItalic(True)
                value_item.setFont(font)
            examples = [format_library_value(example, quote_strings=False) for example in parameter.example_values]
            if examples:
                value_item.setToolTip('Examples:\n' + '\n'.join(examples))
            else:
                value_item.setToolTip('Examples:\n(no observed examples found)')
            self.parameter_table.setItem(row, 0, type_item)
            self.parameter_table.setItem(row, 1, key_item)
            self.parameter_table.setItem(row, 2, value_item)
        self.parameter_table.resizeRowsToContents()
        self._fitTableToRows(self.parameter_table, len(parameters))

    def populateCaseTable(self, entry: typing.Optional[EventLibraryEntry]) -> None:
        case_count = entry.case_count() if entry else 0
        visible = bool(case_count)
        self.case_label.setVisible(visible)
        self.case_values.setVisible(visible)
        if not entry or not case_count:
            self.case_label.setText('')
            self.case_label.setToolTip('')
            self.case_values.setText('')
            self.case_values.setToolTip('')
            return
        self.case_label.setText('Observed switch cases')
        case_tooltip = (
            'EventEditor saw these switch case values in readable EventFlows.\n'
            'Destination branch event names are omitted because they usually are not meaningful.'
        )
        self.case_label.setToolTip(case_tooltip)
        self.case_values.setText(entry.case_value_summary())
        self.case_values.setToolTip(case_tooltip)

    def selectedSourceGroups(self) -> typing.List[str]:
        groups = []
        if self.current_examples_check.isChecked():
            groups.append(SOURCE_GROUP_CURRENT)
        if self.mod_context_enabled and self.mod_examples_check.isChecked():
            groups.append(SOURCE_GROUP_MOD)
        if self.vanilla_examples_check.isChecked():
            groups.append(SOURCE_GROUP_VANILLA)
        return groups

    def setExampleMode(self, show_all_uses: bool) -> None:
        self._show_all_uses = show_all_uses
        self.populateExamples(self._selected_entry)

    def onExampleFiltersChanged(self, *args) -> None:
        self.populateExamples(self._selected_entry)

    def updateExampleFilterControls(self, entry: typing.Optional[EventLibraryEntry]) -> None:
        counts = entry.source_group_counts() if entry else {}
        self.current_examples_check.setText('Current ({})'.format(counts.get(SOURCE_GROUP_CURRENT, 0)))
        self.mod_examples_check.setText('Mod ({})'.format(counts.get(SOURCE_GROUP_MOD, 0)))
        self.mod_examples_check.setVisible(self.mod_context_enabled)
        self.vanilla_examples_check.setText('Vanilla ({})'.format(counts.get(SOURCE_GROUP_VANILLA, 0)))

    def exampleSearchText(self, example: EventLibraryExample, notes: typing.Sequence[str]) -> str:
        pieces = [
            example.display_label(),
            example.source_file,
            example.event_name,
            example.source_label,
        ]
        if example.params:
            for key, value in example.params.items():
                pieces.append(str(key))
                pieces.append(format_library_value(value, quote_strings=False))
        if example.cases:
            pieces.append(' '.join(str(value) for value in sorted(example.cases.keys())))
        pieces.extend(notes)
        return ' '.join(pieces).lower()

    def filteredExamples(self,
                         entry: EventLibraryEntry,
                         groups: typing.Sequence[str],
                         all_mode: bool) -> typing.Tuple[typing.List[EventLibraryExample], int, int]:
        source_examples = entry.examples_for_groups(groups)
        source_count = len(source_examples)
        if all_mode:
            candidates = source_examples
        else:
            candidates = entry.preview_examples(groups, MAX_ENTRY_EXAMPLES)

        needle = self.example_search_edit.text().strip().lower() if all_mode else ''
        unusual_only = bool(all_mode and self.unusual_only_check.isChecked())
        if not needle and not unusual_only:
            return candidates, source_count, source_count

        analysis = entry.usage_analysis()
        filtered = []
        for example in candidates:
            notes = entry.unusual_notes(example, analysis)
            if unusual_only and not notes:
                continue
            if needle and needle not in self.exampleSearchText(example, notes):
                continue
            filtered.append(example)
        return filtered, source_count, len(filtered)

    def populateExamples(self, entry: typing.Optional[EventLibraryEntry]) -> None:
        self.examples_list.clear()
        self.updateExampleFilterControls(entry)

        has_examples = bool(entry and entry.observed_example_count())
        self.examples_label.setVisible(has_examples)
        self.preview_button.setVisible(has_examples)
        self.all_uses_button.setVisible(has_examples)
        self.example_filter_widget.setVisible(has_examples)
        self.example_search_edit.setVisible(bool(has_examples and self._show_all_uses))
        self.unusual_only_check.setVisible(bool(has_examples and self._show_all_uses))
        self.examples_list.setVisible(has_examples)

        if not has_examples or not entry:
            self.examples_label.setText('Observed examples')
            self.details_bottom_spacer.changeSize(0, 0, q.QSizePolicy.Minimum, q.QSizePolicy.Expanding)
            self.detail_layout.invalidate()
            return

        self.preview_button.setEnabled(self._show_all_uses)
        self.all_uses_button.setEnabled(not self._show_all_uses)

        groups = self.selectedSourceGroups()
        examples, source_count, filtered_count = self.filteredExamples(entry, groups, self._show_all_uses)
        group_label = ', '.join(source_group_title(group) for group in groups) if groups else 'no sources'
        if self._show_all_uses:
            if filtered_count != source_count:
                self.examples_label.setText('All observed uses ({} of {}; {})'.format(
                    filtered_count,
                    source_count,
                    group_label,
                ))
            else:
                self.examples_label.setText('All observed uses ({}; {})'.format(source_count, group_label))
        else:
            if len(examples) != source_count:
                self.examples_label.setText('Observed examples (showing {} of {}; {})'.format(
                    len(examples),
                    source_count,
                    group_label,
                ))
            else:
                self.examples_label.setText('Observed examples ({}; {})'.format(source_count, group_label))

        self.details_bottom_spacer.changeSize(0, 0, q.QSizePolicy.Minimum, q.QSizePolicy.Minimum)
        self.detail_layout.invalidate()

        analysis = entry.usage_analysis()
        for example in examples:
            notes = entry.unusual_notes(example, analysis)
            item = q.QListWidgetItem(('[unusual] ' if notes else '') + example.display_label())
            item.setData(qc.Qt.UserRole, example)
            details = []
            if notes:
                details.append('Unusual among observed uses:')
                details.extend(notes)
            if example.params:
                if details:
                    details.append('')
                details.append('Parameters:')
                for key, value in example.params.items():
                    details.append('{}: {}'.format(key, format_library_value(value, quote_strings=False)))
            if example.cases:
                if details:
                    details.append('')
                details.append('Cases: {}'.format(', '.join(str(value) for value in sorted(example.cases.keys()))))
            if notes:
                font = item.font()
                font.setBold(True)
                item.setFont(font)
            item.setToolTip('\n'.join(details) if details else '(no parameters)')
            self.examples_list.addItem(item)

    def onExamplesContextMenu(self, pos) -> None:
        item = self.examples_list.itemAt(pos)
        if not item:
            return
        example = item.data(qc.Qt.UserRole)
        menu = q.QMenu(self)
        go_to_action = menu.addAction('Go to Event')
        go_to_action.setEnabled(bool(
            example and getattr(example, 'source_file', '') and getattr(example, 'event_name', '')
        ))
        action = menu.exec_(self.examples_list.viewport().mapToGlobal(pos))
        if action == go_to_action and go_to_action.isEnabled():
            self.goToExampleRequested.emit(example)

    def filterRows(self, text: str) -> None:
        needle = text.strip().lower()
        first_visible = None
        for row in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(row)
            entry = item.data(0, qc.Qt.UserRole)
            haystack = ' '.join(
                str(item.text(column))
                for column in range(self.tree.columnCount())
            ).lower()
            if isinstance(entry, EventLibraryEntry):
                haystack += ' ' + entry.detail_text().lower()
            hidden = bool(needle and needle not in haystack)
            item.setHidden(hidden)
            if not hidden and first_visible is None:
                first_visible = item

        current = self.tree.currentItem()
        if (not current or current.isHidden()) and first_visible:
            self.tree.setCurrentItem(first_visible)

    def showSkippedFiles(self) -> None:
        dialog = q.QDialog(self, qc.Qt.WindowTitleHint | qc.Qt.WindowSystemMenuHint)
        dialog.setWindowTitle('Skipped files')
        dialog.resize(640, 420)
        layout = q.QVBoxLayout(dialog)
        message = q.QLabel(
            'These files matched the library scan, but EventEditor could not open, decompress, or parse them. '
            'Each row includes the scan stage and the parser/decompression error. '
            'The library can still use entries and examples from files it read successfully.'
        )
        message.setWordWrap(True)
        layout.addWidget(message)
        list_widget = q.QListWidget()
        for error in self.result.errors:
            list_widget.addItem(error)
        layout.addWidget(list_widget, stretch=1)
        buttons = q.QDialogButtonBox(q.QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec_()
