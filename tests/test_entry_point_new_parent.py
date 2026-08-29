import types
import unittest

import PyQt5.QtCore as qc  # type: ignore
from evfl import ActionEvent, Event, EventFlow, Flowchart
from evfl.entry_point import EntryPoint

from eventeditor.event_chooser_dialog import CheckableEventParentListModel
from eventeditor.flowchart_view import FlowchartView


def action_event(name: str) -> Event:
    event = Event()
    event.name = name
    event.data = ActionEvent()
    return event


class EntryPointNewParentTests(unittest.TestCase):
    def test_selected_entry_point_link_is_rerouted_through_the_new_parent(self):
        child = action_event('Child')
        new_parent = action_event('NewParent')
        entry_point = EntryPoint('Start')
        entry_point.main_event.v = child

        flow = EventFlow()
        flow.flowchart = Flowchart()
        flow.flowchart.events = [child, new_parent]
        flow.flowchart.entry_points = [entry_point]

        view = FlowchartView.__new__(FlowchartView)
        view.flow_data = types.SimpleNamespace(flow=flow)
        parents = view._parentNodesForGraphIds([-1000])
        model = CheckableEventParentListModel(None, child, parents)

        self.assertEqual(model.data(model.index(0, 0), qc.Qt.DisplayRole), 'Entry point: Start')

        view._doAddEventAbove(model.getSelectedParents(), child, new_parent)

        self.assertIs(entry_point.main_event.v, new_parent)
        self.assertIs(new_parent.data.nxt.v, child)

    def test_unselected_entry_point_link_keeps_the_new_parent_parallel(self):
        child = action_event('Child')
        new_parent = action_event('NewParent')
        entry_point = EntryPoint('Start')
        entry_point.main_event.v = child

        flow = EventFlow()
        flow.flowchart = Flowchart()
        flow.flowchart.events = [child, new_parent]
        flow.flowchart.entry_points = [entry_point]

        view = FlowchartView.__new__(FlowchartView)
        view.flow_data = types.SimpleNamespace(flow=flow)
        model = CheckableEventParentListModel(
            None,
            child,
            view._parentNodesForGraphIds([-1000]),
        )
        model.setData(model.index(0, 0), qc.Qt.Unchecked, qc.Qt.CheckStateRole)

        view._doAddEventAbove(model.getSelectedParents(), child, new_parent)

        self.assertIs(entry_point.main_event.v, child)
        self.assertIs(new_parent.data.nxt.v, child)


if __name__ == '__main__':
    unittest.main()
