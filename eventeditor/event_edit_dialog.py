import copy
import typing

import eventeditor.event_library as event_library
from eventeditor.event_library_dialog import EventLibraryDialog
from eventeditor.actor_string_list_model import ActorStringListModel
from eventeditor.container_model import (
    ContainerModel,
    is_message_id_key,
)
from eventeditor.container_view import ContainerView
from eventeditor.flow_data import FlowData, FlowDataChangeReason
import eventeditor.totk_zs as totk_zs
import eventeditor.util as util
from evfl import Container, Actor, Event
from evfl.enums import EventType
import evfl.event
import json
import PyQt5.QtCore as qc # type: ignore
import PyQt5.QtWidgets as q # type: ignore

PARAMETER_CLIPBOARD_MIME_TYPE = 'application/x-totk-event-editor-parameters+json'
PARAMETER_CLIPBOARD_FORMAT = 'TOTKEventEditorParameters'
PARAMETER_NODE_TYPE_LABELS = {
    'action': 'action event',
    'switch': 'switch event',
    'subflow': 'subflow event',
}

def _plain_period_finding(field_name: str, value: typing.Any) -> typing.Optional[typing.Dict[str, typing.Any]]:
    if isinstance(value, str) and '.' in value:
        return {'field': field_name, 'value': value}
    return None

def _message_id_period_finding(field_name: str, value: typing.Any) -> typing.Optional[typing.Dict[str, typing.Any]]:
    if not isinstance(value, str) or '.' not in value:
        return None

    separator_index = value.find(':')
    if separator_index == -1:
        return {'field': field_name, 'parts': {'ID': value}}

    msbt_path = value[:separator_index]
    label_id = value[separator_index + 1:]
    parts = {}
    if '.' in msbt_path:
        parts['MSBT'] = msbt_path
    if '.' in label_id:
        parts['ID'] = label_id
    if not parts:
        return None
    return {'field': field_name, 'parts': parts}

def _parameter_period_findings(params: Container) -> typing.List[typing.Dict[str, typing.Any]]:
    findings: typing.List[typing.Dict[str, typing.Any]] = []
    for key, value in params.data.items():
        if is_message_id_key(key):
            finding = _message_id_period_finding(str(key), value)
        else:
            key_lower = str(key).lower()
            if not any(token in key_lower for token in ('path', 'file', 'flowchart')):
                continue
            finding = _plain_period_finding(str(key), value)
        if finding:
            findings.append(finding)
    return findings

def _format_period_finding(finding: typing.Dict[str, typing.Any]) -> str:
    field = finding['field']
    if is_message_id_key(field):
        parts = finding.get('parts') or {}
        lines = ['Message:']
        if 'MSBT' in parts:
            lines.append(f"  MSBT: {parts['MSBT']}")
        if 'ID' in parts:
            lines.append(f"  ID:   {parts['ID']}")
        return '\n'.join(lines)
    value = str(finding['value'])
    return f"{field}: {value}"

def prompt_node_property_period_warning(parent, findings: typing.List[typing.Dict[str, typing.Any]]) -> str:
    dialog = q.QDialog(parent)
    dialog.setWindowTitle('Periods in node properties')
    dialog.setMinimumWidth(520)
    selected_action = {'value': 'back'}

    def choose(action: str) -> None:
        selected_action['value'] = action
        dialog.accept()

    layout = q.QVBoxLayout(dialog)
    layout.setContentsMargins(12, 12, 12, 12)
    layout.setSpacing(12)

    content_layout = q.QHBoxLayout()
    content_layout.setSpacing(12)
    icon_label = q.QLabel()
    icon = dialog.style().standardIcon(q.QStyle.SP_MessageBoxWarning)
    icon_label.setPixmap(icon.pixmap(32, 32))
    icon_label.setAlignment(qc.Qt.AlignTop | qc.Qt.AlignHCenter)
    content_layout.addWidget(icon_label)

    text_layout = q.QVBoxLayout()
    text_layout.setContentsMargins(0, 0, 0, 0)
    message = q.QLabel(
        'One or more paths to external files contains a period.\n'
        'Note that file extensions, like .msbt or .evfl, are not required.'
    )
    message.setWordWrap(True)
    text_layout.addWidget(message)

    details = q.QLabel('\n\n'.join(_format_period_finding(finding) for finding in findings))
    details.setTextFormat(qc.Qt.PlainText)
    details.setTextInteractionFlags(qc.Qt.TextSelectableByMouse)
    details.setWordWrap(True)
    text_layout.addWidget(details)
    content_layout.addLayout(text_layout, stretch=1)
    layout.addLayout(content_layout)

    button_layout = q.QHBoxLayout()
    button_layout.setContentsMargins(0, 4, 0, 0)
    button_layout.setSpacing(8)
    button_layout.addStretch(1)

    back_button = q.QPushButton('Go back')
    back_button.clicked.connect(lambda checked=False: dialog.reject())
    button_layout.addWidget(back_button)
    back_button.setDefault(True)

    ignore_button = q.QPushButton('Ignore')
    ignore_button.clicked.connect(lambda checked=False: choose('ignore'))
    button_layout.addWidget(ignore_button)

    layout.addLayout(button_layout)
    dialog.exec_()
    return selected_action['value']

def set_parameter_clipboard(text: str, node_type: str, params: typing.Dict[str, typing.Any]) -> None:
    mime_data = qc.QMimeData()
    mime_data.setText(text)
    mime_data.setData(PARAMETER_CLIPBOARD_MIME_TYPE, json.dumps({
        'format': PARAMETER_CLIPBOARD_FORMAT,
        'version': 1,
        'node_type': node_type,
        'params': params,
    }).encode('utf-8'))
    q.QApplication.clipboard().setMimeData(mime_data)

def _parse_parameter_payload(data: typing.Any, wrapper_key: str = '') -> typing.Tuple[typing.Dict[str, typing.Any], typing.Optional[str]]:
    source_node_type = None
    if isinstance(data, dict) and data.get('format') == PARAMETER_CLIPBOARD_FORMAT:
        source_node_type = data.get('node_type')
        data = data.get('params')

    if not isinstance(data, dict):
        raise ValueError('Pasted JSON must be an object.')

    if wrapper_key and isinstance(data.get(wrapper_key), dict):
        return data[wrapper_key], source_node_type

    if not wrapper_key and len(data) == 1:
        only_value = next(iter(data.values()))
        if isinstance(only_value, dict):
            return only_value, source_node_type

    return data, source_node_type

def get_parameter_clipboard(wrapper_key: str = '') -> typing.Tuple[typing.Dict[str, typing.Any], typing.Optional[str]]:
    clipboard = q.QApplication.clipboard()
    mime_data = clipboard.mimeData()
    if mime_data and mime_data.hasFormat(PARAMETER_CLIPBOARD_MIME_TYPE):
        payload = json.loads(bytes(mime_data.data(PARAMETER_CLIPBOARD_MIME_TYPE)).decode('utf-8'))
        return _parse_parameter_payload(payload, wrapper_key)

    clipboard_text = clipboard.text().strip()
    try:
        payload = json.loads(clipboard_text)
    except json.JSONDecodeError:
        payload = json.loads(f'{{{clipboard_text}}}')
    return _parse_parameter_payload(payload, wrapper_key)

def confirm_parameter_paste_node_type(parent, source_node_type: typing.Optional[str], target_node_type: str) -> bool:
    if not source_node_type or source_node_type == target_node_type:
        return True

    source_label = PARAMETER_NODE_TYPE_LABELS.get(source_node_type, source_node_type)
    target_label = PARAMETER_NODE_TYPE_LABELS.get(target_node_type, target_node_type)
    response = q.QMessageBox.warning(
        parent,
        'Paste JSON',
        f'This parameter JSON was copied from a {source_label}, but you are pasting it into a {target_label}.\n\nThis is rarely intentional. Continue?',
        q.QMessageBox.Ok | q.QMessageBox.Cancel,
        q.QMessageBox.Cancel,
    )
    return response == q.QMessageBox.Ok

class ActorProxyModel(qc.QIdentityProxyModel):
    def data(self, index, role):
        if index.column() == 0 and role == qc.Qt.DisplayRole:
            return str(self.sourceModel().data(index, qc.Qt.UserRole).identifier)
        return super().data(index, role)

class ActorRelatedEventEditDialog(q.QDialog):
    def __init__(self, parent, flow_data: FlowData, idx: int, attr_list_name: str, attr_name: str) -> None:
        super().__init__(parent, qc.Qt.WindowTitleHint | qc.Qt.WindowSystemMenuHint | qc.Qt.WindowCloseButtonHint)
        self.setWindowTitle('Edit event')
        self.setMinimumWidth(700)
        self.setMinimumHeight(500)
        self.flow_data = flow_data
        self.event_idx = idx
        self.event = self.flow_data.event_model.createIndex(idx, 0).data(qc.Qt.UserRole)
        assert isinstance(self.event.data, evfl.event.ActionEvent) or isinstance(self.event.data, evfl.event.SwitchEvent)
        self.is_switch = isinstance(self.event.data, evfl.event.SwitchEvent)
        self.attr_list_name = attr_list_name
        self.attr_name = attr_name
        self._library_results = {}  # type: typing.Dict[typing.Tuple[str, str, str, str, int], event_library.EventLibraryResult]

        if self.is_switch:
            self.setWindowTitle('Edit switch event')
        else:
            self.setWindowTitle('Edit action event')

        self.param_model = ContainerModel(self)
        if not self.event.data.params:
            self.event.data.params = Container()
        self.modified_params: Container = copy.deepcopy(self.event.data.params)
        self.param_model.set(self.modified_params)
        self.attr_model = ActorStringListModel(self, [])
        util.connect_model_change_signals(self.attr_model, self.flow_data, FlowDataChangeReason.Actors)

        self.createActorCbox()
        self.createAttrCbox()
        self.createParametersView()

        row = q.QHBoxLayout()
        row.addWidget(self.actor_cbox, stretch=1)
        separator = q.QLabel('::')
        row.addWidget(separator)
        row.addWidget(self.attr_cbox, stretch=1)
        row.addWidget(self.library_btn)

        layout = q.QVBoxLayout(self)
        layout.addLayout(row)
        layout.addWidget(self.param_view)
        btn_box = q.QDialogButtonBox(q.QDialogButtonBox.Save | q.QDialogButtonBox.Cancel)
        layout.addWidget(btn_box)

        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)

    def createActorCbox(self) -> None:
        self.actor_proxy_model = ActorProxyModel(self)
        self.actor_proxy_model.setSourceModel(self.flow_data.actor_model)
        self.actor_cbox = q.QComboBox()
        self.actor_cbox.currentIndexChanged.connect(self.onActorSelected)
        self.actor_cbox.setModel(self.actor_proxy_model)
        actor = self.event.data.actor.v
        self.actor_cbox.setCurrentIndex(self.actor_cbox.findData(actor))

    def createAttrCbox(self) -> None:
        self.attr_cbox = q.QComboBox()
        self.attr_cbox.setModel(self.attr_model)
        attr = getattr(self.event.data, self.attr_name).v
        self.attr_cbox.setCurrentIndex(self.attr_cbox.findData(attr))
        self.library_btn = q.QPushButton('Library...')
        self.library_btn.setStyleSheet('padding: 2px 5px;')
        self.library_btn.clicked.connect(self.onLibraryRequested)

    def createParametersView(self) -> None:
        self.param_view = ContainerView(None, self.param_model, self.flow_data, show_json_tools=True)
        self.param_view.copyJsonRequested.connect(self.onCopyJsonRequested)
        self.param_view.pasteJsonRequested.connect(self.onPasteJsonRequested)
        self.param_view.addHeaderButton('Add Missing', self.onAddMissingParametersRequested)
        self.param_view.addHeaderButton('Remove Excess', self.onRemoveExcessParametersRequested)

    def parameterClipboardNodeType(self) -> str:
        return 'switch' if self.is_switch else 'action'

    def currentLibraryKind(self) -> str:
        return event_library.EVENT_LIBRARY_QUERY if self.is_switch else event_library.EVENT_LIBRARY_ACTION

    def libraryKindLabel(self, kind: str) -> str:
        return 'Queries' if kind == event_library.EVENT_LIBRARY_QUERY else 'Actions'

    def actorLibraryLabel(self, actor: Actor, kind: str) -> str:
        return '{} - {}'.format(actor.identifier.name, self.libraryKindLabel(kind))

    def libraryResultCacheKey(self, actor: Actor, kind: str) -> typing.Tuple[str, str, str, str, int]:
        flow_path = getattr(self.flow_data, 'flow_path', '')
        vanilla_romfs = totk_zs.get_romfs_path()
        return (
            actor.identifier.name,
            kind,
            str(flow_path or ''),
            str(vanilla_romfs or ''),
            id(self.flow_data.flow) if self.flow_data.flow else 0,
        )

    def cachedLibraryResult(self, actor: Actor, kind: str) -> typing.Optional[event_library.EventLibraryResult]:
        return self._library_results.get(self.libraryResultCacheKey(actor, kind))

    def rememberLibraryResult(self, actor: Actor, kind: str, result: event_library.EventLibraryResult) -> None:
        self._library_results[self.libraryResultCacheKey(actor, kind)] = result

    def currentNodeTypeName(self) -> str:
        node_type = None
        current_index = self.attr_cbox.currentIndex()
        if current_index >= 0:
            model_index = self.attr_model.index(current_index, 0)
            if model_index.isValid():
                node_type = model_index.data(qc.Qt.UserRole)
        if node_type is None:
            node_type = self.attr_cbox.currentData()
        node_name = getattr(node_type, 'v', node_type)
        if node_name:
            return str(node_name).strip()
        return self.attr_cbox.currentText().strip()

    def currentLibraryEntry(self) -> typing.Optional[event_library.EventLibraryEntry]:
        actor = self.actor_cbox.currentData()
        node_name = self.currentNodeTypeName()
        if not actor or not node_name:
            return None
        kind = self.currentLibraryKind()
        result = self.buildLibraryResult(actor, kind)
        for entry in result.entries:
            if entry.name.strip() == node_name:
                return entry
        return None

    def currentActorNodeLabel(self) -> str:
        actor = self.actor_cbox.currentData()
        actor_name = actor.identifier.name if actor else '(no actor)'
        node_name = self.currentNodeTypeName() or '(no node type)'
        return '{}.{}'.format(actor_name, node_name)

    def promptParameterComparison(self,
                                  title: str,
                                  message: str,
                                  rows: typing.List[str],
                                  apply_enabled: bool) -> bool:
        dialog = q.QDialog(self, qc.Qt.WindowTitleHint | qc.Qt.WindowSystemMenuHint | qc.Qt.WindowCloseButtonHint)
        dialog.setWindowTitle(title)
        dialog.resize(520, 280)
        layout = q.QVBoxLayout(dialog)
        label = q.QLabel(message)
        label.setWordWrap(True)
        layout.addWidget(label)

        list_widget = q.QListWidget()
        for row in rows:
            list_widget.addItem(row)
        layout.addWidget(list_widget, stretch=1)

        button_box = q.QDialogButtonBox(q.QDialogButtonBox.Cancel if apply_enabled else q.QDialogButtonBox.Close)
        if apply_enabled:
            button_box.addButton('Apply', q.QDialogButtonBox.AcceptRole)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)
        result = dialog.exec_()
        return bool(apply_enabled and result == q.QDialog.Accepted)

    def blankLibraryParameterValue(self, parameter: event_library.EventLibraryParameter) -> typing.Any:
        for type_name in parameter.defined_types:
            value = event_library.default_value_for_type(type_name)
            if value is not None:
                return value

        seed_value = parameter.seed_value()
        if isinstance(seed_value, bool):
            return False
        if isinstance(seed_value, int):
            return 0
        if isinstance(seed_value, float):
            return 0.0
        if isinstance(seed_value, list):
            return []
        return ''

    def promptAddMissingParameters(self,
                                   actor_node: str,
                                   missing: typing.List[event_library.EventLibraryParameter],
                                   entry: event_library.EventLibraryEntry
                                   ) -> typing.Tuple[str, typing.Optional[event_library.EventLibraryExample]]:
        dialog = q.QDialog(self, qc.Qt.WindowTitleHint | qc.Qt.WindowSystemMenuHint | qc.Qt.WindowCloseButtonHint)
        dialog.setWindowTitle('Add Missing Parameters')
        dialog.resize(620, 360)
        layout = q.QVBoxLayout(dialog)

        message = q.QLabel('These parameters are missing compared with vanilla {}.'.format(actor_node))
        message.setWordWrap(True)
        layout.addWidget(message)

        example_combo = q.QComboBox()
        example_combo.setEditable(True)
        example_combo.setInsertPolicy(q.QComboBox.NoInsert)
        observed_examples = entry.all_observed_examples()
        for example in observed_examples:
            example_combo.addItem(example.display_label(), example)
        if example_combo.completer():
            example_combo.completer().setFilterMode(qc.Qt.MatchContains)
            example_combo.completer().setCompletionMode(q.QCompleter.PopupCompletion)
        if not observed_examples:
            example_combo.addItem('(no observed examples found)', None)
            example_combo.setEnabled(False)
        layout.addWidget(q.QLabel('Example values'))
        layout.addWidget(example_combo)

        table = q.QTableWidget()
        table.setColumnCount(3)
        table.setHorizontalHeaderLabels(['Type', 'Key', 'Value'])
        table.verticalHeader().hide()
        table.setEditTriggers(q.QAbstractItemView.NoEditTriggers)
        table.setSelectionMode(q.QAbstractItemView.NoSelection)
        table.setRowCount(len(missing))
        for row, parameter in enumerate(missing):
            type_item = q.QTableWidgetItem(parameter.type_label())
            key_item = q.QTableWidgetItem(parameter.name)
            type_item.setFlags(type_item.flags() & ~qc.Qt.ItemIsEditable)
            key_item.setFlags(key_item.flags() & ~qc.Qt.ItemIsEditable)
            table.setItem(row, 0, type_item)
            table.setItem(row, 1, key_item)
        table.horizontalHeader().setSectionResizeMode(0, q.QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, q.QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, q.QHeaderView.Stretch)
        table.resizeRowsToContents()
        layout.addWidget(table, stretch=1)

        def updatePreviewValues(*args) -> None:
            selected_example = example_combo.currentData()
            preview_values = dict(self.valuesForMissingParameters(missing, 'all', selected_example))
            for row, parameter in enumerate(missing):
                value = preview_values.get(parameter.name, '')
                value_item = q.QTableWidgetItem(event_library.format_library_value(value, quote_strings=False))
                value_item.setFlags(value_item.flags() & ~qc.Qt.ItemIsEditable)
                font = value_item.font()
                font.setItalic(True)
                value_item.setFont(font)
                table.setItem(row, 2, value_item)

        example_combo.currentIndexChanged.connect(updatePreviewValues)
        updatePreviewValues()

        choice = {'action': ''}  # type: typing.Dict[str, str]
        button_box = q.QDialogButtonBox(q.QDialogButtonBox.Cancel)
        add_blank_button = button_box.addButton('Add Blank', q.QDialogButtonBox.ActionRole)
        add_all_button = button_box.addButton('Add All', q.QDialogButtonBox.AcceptRole)

        def choose(action: str) -> None:
            choice['action'] = action
            dialog.accept()

        add_blank_button.clicked.connect(lambda: choose('blank'))
        add_all_button.clicked.connect(lambda: choose('all'))
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)

        if dialog.exec_() != q.QDialog.Accepted:
            return '', None
        return choice['action'], example_combo.currentData()

    def valuesForMissingParameters(self,
                                   missing: typing.List[event_library.EventLibraryParameter],
                                   action: str,
                                   example: typing.Optional[event_library.EventLibraryExample]
                                   ) -> typing.List[typing.Tuple[str, typing.Any]]:
        values = []
        example_params = example.params if example and example.params else {}
        for parameter in missing:
            if action == 'all' and parameter.name in example_params:
                value = copy.deepcopy(example_params[parameter.name])
            else:
                value = self.blankLibraryParameterValue(parameter)
            values.append((parameter.name, value))
        return values

    def onAddMissingParametersRequested(self) -> None:
        entry = self.currentLibraryEntry()
        actor_node = self.currentActorNodeLabel()
        if not entry:
            self.promptParameterComparison(
                'Add Missing Parameters',
                'No library entry was found for {}.'.format(actor_node),
                ['The selected node type is not present in the actor library.'],
                False,
            )
            return
        if not entry.has_vanilla_baseline():
            self.promptParameterComparison(
                'Add Missing Parameters',
                'No vanilla parameter information was found for {}.'.format(actor_node),
                ['No vanilla baseline is available for this actor node.'],
                False,
            )
            return

        existing_keys = set(self.modified_params.data.keys())
        missing = [parameter for parameter in entry.vanilla_parameters() if parameter.name not in existing_keys]
        if not missing:
            if not entry.vanilla_parameters():
                message = '{} has no missing parameters; vanilla expects no parameters.'.format(actor_node)
                rows = ['Vanilla baseline has no parameters for this actor node.']
            else:
                message = '{} already has all parameters known from vanilla.'.format(actor_node)
                rows = ['No missing parameters.']
            self.promptParameterComparison(
                'Add Missing Parameters',
                message,
                rows,
                False,
            )
            return

        action, example = self.promptAddMissingParameters(actor_node, missing, entry)
        if not action:
            return

        additions = self.valuesForMissingParameters(missing, action, example)
        for key, value in additions:
            self.modified_params.data[key] = copy.deepcopy(value)
        self.param_model.set(self.modified_params)

    def onRemoveExcessParametersRequested(self) -> None:
        entry = self.currentLibraryEntry()
        actor_node = self.currentActorNodeLabel()
        if not entry:
            self.promptParameterComparison(
                'Remove Excess Parameters',
                'No library entry was found for {}.'.format(actor_node),
                ['The selected node type is not present in the actor library.'],
                False,
            )
            return
        if not entry.has_vanilla_baseline():
            self.promptParameterComparison(
                'Remove Excess Parameters',
                'No vanilla parameter information was found for {}.'.format(actor_node),
                ['No vanilla baseline is available for this actor node.'],
                False,
            )
            return

        vanilla_keys = set(entry.vanilla_parameter_names())
        excess = [key for key in self.modified_params.data.keys() if key not in vanilla_keys]
        if not excess:
            if not vanilla_keys:
                message = '{} already has no parameters, matching vanilla.'.format(actor_node)
                rows = ['Vanilla baseline has no parameters for this actor node.']
            else:
                message = '{} has no parameters outside the vanilla set.'.format(actor_node)
                rows = ['No excess parameters.']
            self.promptParameterComparison(
                'Remove Excess Parameters',
                message,
                rows,
                False,
            )
            return

        if not self.promptParameterComparison(
            'Remove Excess Parameters',
            'These parameters are not present in vanilla {}.'.format(actor_node),
            list(excess),
            True,
        ):
            return

        for key in excess:
            self.modified_params.data.pop(key, None)
        self.param_model.set(self.modified_params)

    def onCopyJsonRequested(self) -> None:
        toClipboard = json.dumps(self.modified_params.data)

        if self.attr_cbox.currentData():
            params = dict()
            params[str(self.attr_cbox.currentData().v)] = self.modified_params.data
            # Remove outer curly brackets for convenience
            toClipboard = json.dumps(params)[1:-1]

        set_parameter_clipboard(toClipboard, self.parameterClipboardNodeType(), self.modified_params.data)

    def onPasteJsonRequested(self) -> None:
        try:
            wrapper_key = self.attr_cbox.currentData().v if self.attr_cbox.currentData() else ''
            params, source_node_type = get_parameter_clipboard(wrapper_key)
            if not confirm_parameter_paste_node_type(self, source_node_type, self.parameterClipboardNodeType()):
                return

            self.modified_params.data.clear()
            for param in params:
                self.modified_params.data[param] = params[param]
            self.param_model.set(self.modified_params)

        except:
            q.QMessageBox.critical(self, 'Paste JSON', 'Failed to paste clipboard data as parameters.')

    def onActorSelected(self, actor_idx: int) -> None:
        if actor_idx == -1:
            return
        self.attr_model.set(getattr(self.actor_cbox.currentData(), self.attr_list_name))

    def onLibraryRequested(self) -> None:
        actor = self.actor_cbox.currentData()
        if not actor:
            return

        kind = self.currentLibraryKind()
        force_rebuild = False
        while True:
            result = self.buildLibraryResult(actor, kind, force_rebuild)
            if not result.entries:
                message = 'No library entries were found for {}.'.format(self.actorLibraryLabel(actor, kind))
                if result.errors:
                    message += (
                        '\n\n{} files were skipped while looking for examples. '
                        'This usually means EventEditor could not open, decompress, or parse those files, '
                        'but any entries it did find are still usable.'
                    ).format(len(result.errors))
                q.QMessageBox.information(self, 'Event library', message)
                return

            dialog = EventLibraryDialog(self, actor.identifier.name, kind, result)
            dialog.goToExampleRequested.connect(self.onLibraryExampleGoToRequested)
            if not dialog.exec_():
                if dialog.rebuildRequested():
                    force_rebuild = True
                    continue
                return
            entry = dialog.selectedEntry()
            if entry:
                self.addLibraryEntryToActor(entry)
            return

    def buildLibraryResult(self, actor: Actor, kind: str, force_rebuild: bool = False) -> event_library.EventLibraryResult:
        cached_result = self.cachedLibraryResult(actor, kind)
        if not force_rebuild and cached_result:
            return cached_result

        flow_path = getattr(self.flow_data, 'flow_path', '')
        current_revision = getattr(self.flow_data, 'revision', 0)
        vanilla_romfs = totk_zs.get_romfs_path()
        cache_current = event_library.is_actor_event_library_cache_current(
            actor.identifier.name,
            kind,
            current_flow=self.flow_data.flow,
            flow_path=flow_path,
            vanilla_romfs=vanilla_romfs,
            current_revision=current_revision,
        )
        wait_dialog = None
        wait_cursor_set = False
        if force_rebuild or not cache_current:
            wait_dialog = self.showLibraryBuildDialog(self.actorLibraryLabel(actor, kind))
            q.QApplication.setOverrideCursor(qc.Qt.WaitCursor)
            wait_cursor_set = True

        try:
            result = event_library.build_actor_event_library(
                actor.identifier.name,
                kind,
                current_flow=self.flow_data.flow,
                flow_path=flow_path,
                vanilla_romfs=vanilla_romfs,
                current_revision=current_revision,
                force_rebuild=force_rebuild,
            )
            self.rememberLibraryResult(actor, kind, result)
            return result
        finally:
            if wait_cursor_set:
                q.QApplication.restoreOverrideCursor()
            if wait_dialog:
                wait_dialog.close()
                wait_dialog.deleteLater()

    def showLibraryBuildDialog(self, library_label: str) -> q.QDialog:
        dialog = q.QDialog(self, qc.Qt.WindowTitleHint)
        dialog.setWindowTitle('Event library')
        dialog.setWindowModality(qc.Qt.WindowModal)
        layout = q.QVBoxLayout(dialog)
        message = q.QLabel('Building library for "{}"...'.format(library_label))
        message.setAlignment(qc.Qt.AlignCenter)
        layout.addWidget(message)
        dialog.setFixedSize(320, 84)
        dialog.show()
        q.QApplication.processEvents()
        return dialog

    def onLibraryExampleGoToRequested(self, example) -> None:
        parent = self.parent()
        if hasattr(parent, 'goToLibraryExample'):
            parent.goToLibraryExample(example)
            return
        q.QMessageBox.information(
            self,
            'Go to Event',
            'This view cannot open library examples.',
        )

    def addLibraryEntryToActor(self, entry: event_library.EventLibraryEntry) -> None:
        actor = self.actor_cbox.currentData()
        if not actor:
            return

        if not self.attr_model.has(entry.name):
            self.attr_model.append(entry.name)
            self.flow_data.actor_model.refresh()

        for row in range(self.attr_model.rowCount(qc.QModelIndex())):
            index = self.attr_model.index(row, 0)
            value = index.data(qc.Qt.UserRole)
            if value and getattr(value, 'v', '') == entry.name:
                self.attr_cbox.setCurrentIndex(row)
                break

        default_params = entry.default_params()
        if default_params and not self.modified_params.data:
            self.modified_params.data.update(default_params)
            self.param_model.set(self.modified_params)

    def collectPeriodFindings(self) -> typing.List[typing.Dict[str, typing.Any]]:
        return _parameter_period_findings(self.modified_params)

    def handlePeriodsBeforeClose(self) -> str:
        findings = self.collectPeriodFindings()
        if not findings:
            return 'ignore'
        return prompt_node_property_period_warning(self, findings)

    def prepareNodeEditCommit(self) -> None:
        parent = self.parent()
        if hasattr(parent, 'prepareNodeEditCommit'):
            parent.prepareNodeEditCommit(self.event, self.event_idx)

    def accept(self) -> None:
        new_actor = self.actor_cbox.currentData()
        new_attr = self.attr_cbox.currentData()
        if not new_actor or not new_attr:
            q.QMessageBox.critical(self, 'Invalid data', 'Please select an actor and a function.')
            return

        period_action = self.handlePeriodsBeforeClose()
        if period_action == 'back':
            return

        previous_actor = self.event.data.actor.v
        previous_attr = getattr(self.event.data, self.attr_name).v
        self.event.data.actor.v = new_actor
        attr = getattr(self.event.data, self.attr_name)
        attr.v = new_attr

        reason = FlowDataChangeReason.Unknown
        if previous_actor != new_actor or previous_attr != new_attr:
            reason |= FlowDataChangeReason.Events
        if self.event.data.params.data != self.modified_params.data:
            reason |= FlowDataChangeReason.EventParameters

        self.event.data.params = self.modified_params

        self.prepareNodeEditCommit()
        self.flow_data.flowDataChanged.emit(reason)
        super().accept()

    def reject(self) -> None:
        period_action = self.handlePeriodsBeforeClose()
        if period_action == 'back':
            return
        super().reject()

class SubFlowEventEditDialog(q.QDialog):
    def __init__(self, parent, flow_data: FlowData, idx: int) -> None:
        super().__init__(parent, qc.Qt.WindowTitleHint | qc.Qt.WindowSystemMenuHint | qc.Qt.WindowCloseButtonHint)
        self.setWindowTitle('Edit event')
        self.setMinimumWidth(500)
        self.flow_data = flow_data
        self.event_idx = idx
        self.event = self.flow_data.event_model.createIndex(idx, 0).data(qc.Qt.UserRole)
        assert self.flow_data.flow and isinstance(self.event.data, evfl.event.SubFlowEvent)
        self.param_model = ContainerModel(self)
        if not self.event.data.params:
            self.event.data.params = Container()
        self.modified_params = copy.deepcopy(self.event.data.params)
        self.param_model.set(self.modified_params)

        form = q.QFormLayout()

        self.flowchart_ledit = q.QLineEdit()
        self.flowchart_ledit.setText(self.event.data.res_flowchart_name)
        self.flowchart_ledit.setPlaceholderText(f'{self.flow_data.flow.name} (edit to specify an external flowchart)')
        form.addRow('&Flowchart:', self.flowchart_ledit)
        self.entry_point_ledit = q.QLineEdit()
        self.entry_point_ledit.setText(self.event.data.entry_point_name)
        self.entry_point_ledit.setPlaceholderText('Entry point name (mandatory)')
        form.addRow('&Entry point:', self.entry_point_ledit)

        btn_box = q.QDialogButtonBox(q.QDialogButtonBox.Save | q.QDialogButtonBox.Cancel);
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        self.param_view = ContainerView(None, self.param_model, self.flow_data, show_json_tools=True)
        self.param_view.copyJsonRequested.connect(self.onCopyJsonRequested)
        self.param_view.pasteJsonRequested.connect(self.onPasteJsonRequested)
        layout = q.QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.param_view)
        layout.addWidget(btn_box)

    def onCopyJsonRequested(self) -> None:
        set_parameter_clipboard(json.dumps(self.modified_params.data), 'subflow', self.modified_params.data)

    def onPasteJsonRequested(self) -> None:
        try:
            params, source_node_type = get_parameter_clipboard()
            if not confirm_parameter_paste_node_type(self, source_node_type, 'subflow'):
                return

            self.modified_params.data.clear()
            for param in params:
                self.modified_params.data[param] = params[param]
            self.param_model.set(self.modified_params)

        except Exception:
            q.QMessageBox.critical(self, 'Paste JSON', 'Failed to paste clipboard data as parameters.')

    def collectPeriodFindings(self) -> typing.List[typing.Dict[str, typing.Any]]:
        findings = []
        flowchart_finding = _plain_period_finding('Flowchart', self.flowchart_ledit.text())
        if flowchart_finding:
            findings.append(flowchart_finding)
        findings.extend(_parameter_period_findings(self.modified_params))
        return findings

    def handlePeriodsBeforeClose(self) -> str:
        findings = self.collectPeriodFindings()
        if not findings:
            return 'ignore'
        return prompt_node_property_period_warning(self, findings)

    def prepareNodeEditCommit(self) -> None:
        parent = self.parent()
        if hasattr(parent, 'prepareNodeEditCommit'):
            parent.prepareNodeEditCommit(self.event, self.event_idx)

    def accept(self) -> None:
        period_action = self.handlePeriodsBeforeClose()
        if period_action == 'back':
            return
        new_flowchart = self.flowchart_ledit.text()
        new_ep = self.entry_point_ledit.text()
        if not new_ep:
            q.QMessageBox.critical(self, 'Invalid data', 'The entry point name cannot be empty.')
            return

        prev_flowchart = self.event.data.res_flowchart_name
        prev_ep = self.event.data.entry_point_name
        self.event.data.res_flowchart_name = new_flowchart
        self.event.data.entry_point_name = new_ep

        reason = FlowDataChangeReason.Unknown
        if prev_flowchart != new_flowchart or prev_ep != new_ep:
            reason |= FlowDataChangeReason.Events
        if self.event.data.params.data != self.modified_params.data:
            reason |= FlowDataChangeReason.EventParameters

        self.event.data.params = self.modified_params

        self.prepareNodeEditCommit()
        self.flow_data.flowDataChanged.emit(reason)
        super().accept()

    def reject(self) -> None:
        period_action = self.handlePeriodsBeforeClose()
        if period_action == 'back':
            return
        super().reject()

def make_event_edit_dialog(parent, flow_data: FlowData, idx: int) -> typing.Optional[q.QDialog]:
    model = flow_data.event_model
    event = flow_data.event_model.data(model.createIndex(idx, 0), qc.Qt.UserRole)
    if isinstance(event.data, evfl.event.ActionEvent):
        return ActorRelatedEventEditDialog(parent, flow_data, idx, 'actions', 'actor_action')
    if isinstance(event.data, evfl.event.SwitchEvent):
        return ActorRelatedEventEditDialog(parent, flow_data, idx, 'queries', 'actor_query')
    if isinstance(event.data, evfl.event.SubFlowEvent):
        return SubFlowEventEditDialog(parent, flow_data, idx)
    return None

def show_event_editor(parent, flow_data: FlowData, idx: int) -> bool:
    dialog = make_event_edit_dialog(parent, flow_data, idx)
    if dialog:
        dialog.exec_()
        return True

    q.QMessageBox.information(parent, 'Edit event', 'This event has no editable property.')
    return False
