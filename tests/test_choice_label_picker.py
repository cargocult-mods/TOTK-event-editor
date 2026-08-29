import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from evfl import Actor, Container, Event, EventFlow, Flowchart
from evfl.common import StringHolder
from evfl.event import ActionEvent, SwitchEvent
from PyQt5 import QtCore as qc  # type: ignore
from PyQt5 import QtWidgets as q  # type: ignore

from eventeditor.choice_label_picker import (
    ChoiceLabelPickerDialog,
    four_digit_choice_label_entries,
)
from eventeditor.container_model import ContainerModelColumn
from eventeditor.event_edit_dialog import ActorRelatedEventEditDialog
from eventeditor.flow_data import FlowData
import eventeditor.mals as mals


class MessageArchiveParent(q.QWidget):
    def __init__(self, path='test.sarc'):
        super().__init__()
        self.path = path

    def getMessageArchivePath(self):
        return self.path


def make_flow(event_data):
    flow = EventFlow()
    flow.name = 'ChoiceTest'
    flow.flowchart = Flowchart()
    flow.flowchart.name = flow.name

    actor = Actor()
    actor.identifier.name = 'EventFlowAction'
    actor.actions = [StringHolder('EventTalk')]
    actor.queries = [StringHolder('EventQuery')]

    event = Event()
    event.name = 'Event0'
    event.data = event_data
    event.data.actor.v = actor
    if isinstance(event_data, ActionEvent):
        event.data.actor_action.v = actor.actions[0]
    else:
        event.data.actor_query.v = actor.queries[0]
    event.data.params = Container()
    event.data.params.data = {
        'MessageID': 'EventFlowMsg/CC_Test:talk_0000',
        'ChoiceLabel1': 7,
        'NotAChoice': 12,
    }

    flow.flowchart.actors = [actor]
    flow.flowchart.events = [event]
    flow.flowchart.entry_points = []
    return flow


class ChoiceLabelPickerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = q.QApplication.instance() or q.QApplication([])

    def test_filters_exact_four_digit_labels_and_sorts_descending(self):
        entries = four_digit_choice_label_entries({
            '0007': 'Seven',
            '1200': 'Twelve hundred',
            '9999': 'Last',
            '007': 'Too short',
            'choice_1234': 'Wrong shape',
            '10000': 'Too long',
        })
        self.assertEqual(entries, [
            ('9999', 'Last'),
            ('1200', 'Twelve hundred'),
            ('0007', 'Seven'),
        ])

    def test_picker_has_two_columns_and_accepts_double_click(self):
        dialog = ChoiceLabelPickerDialog(None, [('0012', 'Twelve'), ('0004', 'Four')])
        self.assertEqual(dialog.table.horizontalHeaderItem(0).text(), 'Label')
        self.assertEqual(dialog.table.horizontalHeaderItem(1).text(), 'Contents')
        self.assertEqual(dialog.table.item(0, 0).text(), '0012')

        dialog.table.selectRow(1)
        dialog.table.cellDoubleClicked.emit(1, 1)
        self.assertEqual(dialog.result(), q.QDialog.Accepted)
        self.assertEqual(dialog.selectedLabel(), '0004')

    def test_action_dialog_adds_picker_only_for_choice_labels(self):
        flow_data = FlowData()
        flow_data.auto_save.save = lambda flow: None
        flow_data.setFlow(make_flow(ActionEvent()), emit_file_loaded=False)
        parent = MessageArchiveParent()
        dialog = ActorRelatedEventEditDialog(
            parent, flow_data, 0, 'actions', 'actor_action')

        choice_menu = q.QMenu()
        choice_index = dialog.param_model.index(1, ContainerModelColumn.Value)
        dialog.addChoiceLabelPickerAction(choice_menu, choice_index)
        self.assertEqual([action.text() for action in choice_menu.actions()], ['Pick from existing...'])

        ordinary_menu = q.QMenu()
        ordinary_index = dialog.param_model.index(2, ContainerModelColumn.Value)
        dialog.addChoiceLabelPickerAction(ordinary_menu, ordinary_index)
        self.assertEqual(ordinary_menu.actions(), [])

    def test_switch_dialog_does_not_register_choice_label_picker(self):
        flow_data = FlowData()
        flow_data.auto_save.save = lambda flow: None
        flow_data.setFlow(make_flow(SwitchEvent()), emit_file_loaded=False)
        parent = MessageArchiveParent()
        dialog = ActorRelatedEventEditDialog(
            parent, flow_data, 0, 'queries', 'actor_query')
        self.assertNotIn(dialog.addChoiceLabelPickerAction, dialog.param_view.action_builders)

    def test_picking_uses_message_id_msbt_and_preserves_integer_type(self):
        flow_data = FlowData()
        flow_data.auto_save.save = lambda flow: None
        flow_data.setFlow(make_flow(ActionEvent()), emit_file_loaded=False)
        parent = MessageArchiveParent('/tmp/USen.Product.110.sarc')
        dialog = ActorRelatedEventEditDialog(
            parent,
            flow_data,
            0,
            'actions',
            'actor_action',
        )
        choice_index = dialog.param_model.index(1, ContainerModelColumn.Value)

        with mock.patch.object(
            mals,
            'load_messages_for_msbt',
            return_value={'0002': 'Two', '0042': 'Forty two'},
        ) as load_messages, mock.patch(
            'eventeditor.event_edit_dialog.ChoiceLabelPickerDialog.exec_',
            return_value=q.QDialog.Accepted,
        ), mock.patch(
            'eventeditor.event_edit_dialog.ChoiceLabelPickerDialog.selectedLabel',
            return_value='0042',
        ):
            dialog.onPickChoiceLabelRequested(choice_index)

        load_messages.assert_called_once_with(
            '/tmp/USen.Product.110.sarc',
            'EventFlowMsg/CC_Test',
            show_tags=False,
        )
        self.assertEqual(dialog.modified_params.data['ChoiceLabel1'], 42)
        self.assertIs(type(dialog.modified_params.data['ChoiceLabel1']), int)

    def test_load_messages_for_msbt_uses_relevant_file_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive_path = os.path.join(tmp, 'USen.Product.110.sarc')
            with open(archive_path, 'wb') as archive:
                archive.write(b'archive')

            with mock.patch.object(mals, '_iter_msbt_files', return_value=[
                ('EventFlowMsg/CC_Other.msbt', b'other'),
                ('EventFlowMsg/CC_Test.msbt', b'target'),
            ]), mock.patch.object(
                mals,
                '_parse_msbt',
                side_effect=lambda data, show_tags: {
                    b'other': {'0001': 'Wrong file'},
                    b'target': {'0002': 'Right file'},
                }[data],
            ):
                messages = mals.load_messages_for_msbt(
                    archive_path,
                    'EventFlowMsg/CC_Test',
                    show_tags=False,
                )

        self.assertEqual(messages, {'0002': 'Right file'})


if __name__ == '__main__':
    unittest.main()
