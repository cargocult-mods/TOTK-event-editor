import copy
import typing

from eventeditor.actor_string_list_model import ActorStringListModel
from eventeditor.container_model import (
    ContainerModel,
    is_message_id_key,
)
from eventeditor.container_view import ContainerView
from eventeditor.flow_data import FlowData, FlowDataChangeReason
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
        self.event = self.flow_data.event_model.createIndex(idx, 0).data(qc.Qt.UserRole)
        assert isinstance(self.event.data, evfl.event.ActionEvent) or isinstance(self.event.data, evfl.event.SwitchEvent)
        self.is_switch = isinstance(self.event.data, evfl.event.SwitchEvent)
        self.attr_list_name = attr_list_name
        self.attr_name = attr_name

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

    def createParametersView(self) -> None:
        self.param_view = ContainerView(None, self.param_model, self.flow_data, show_json_tools=True)
        self.param_view.copyJsonRequested.connect(self.onCopyJsonRequested)
        self.param_view.pasteJsonRequested.connect(self.onPasteJsonRequested)

    def parameterClipboardNodeType(self) -> str:
        return 'switch' if self.is_switch else 'action'

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

    def collectPeriodFindings(self) -> typing.List[typing.Dict[str, typing.Any]]:
        return _parameter_period_findings(self.modified_params)

    def handlePeriodsBeforeClose(self) -> str:
        findings = self.collectPeriodFindings()
        if not findings:
            return 'ignore'
        return prompt_node_property_period_warning(self, findings)

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
