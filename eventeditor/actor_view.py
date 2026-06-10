from enum import IntEnum, auto
import typing

import eventeditor.actor_xml as axml
from eventeditor.actor_model import ActorModelColumn
from eventeditor.actor_string_list_model import ActorStringListModel
from eventeditor.actor_string_list_view import ActorActionListView, ActorQueryListView
import eventeditor.container_xml as cxml
from eventeditor.container_model import ContainerModel
from eventeditor.container_view import ContainerView
from eventeditor.flow_data import FlowDataChangeReason
from eventeditor.sortable_proxy_model import SortableHeaderProxyModel
import eventeditor.util as util
from evfl import Container, EventFlow, Actor, ActorIdentifier
from evfl.common import StringHolder
from evfl.entry_point import EntryPoint
import PyQt5.QtCore as qc # type: ignore
import PyQt5.QtWidgets as q # type: ignore

class ActorEditDialog(q.QDialog):
    def __init__(self, parent, flow_data, idx: int) -> None:
        super().__init__(parent, qc.Qt.WindowTitleHint | qc.Qt.WindowSystemMenuHint)
        self.setWindowTitle('Edit actor')
        self.setMinimumWidth(500)
        self.flow_data = flow_data
        self.mapper = q.QDataWidgetMapper(self)
        self.mapper.setSubmitPolicy(q.QDataWidgetMapper.ManualSubmit)
        self.mapper.setModel(flow_data.actor_model)

        self.initWidgets(idx)
        self.initLayout()
        self.connectWidgets()

        self.mapper.setCurrentIndex(idx)
        self.prev_identifier = ActorIdentifier(self.name_edit.text(), self.sub_name_edit.text())

    def initWidgets(self, idx: int) -> None:
        self.form = q.QFormLayout()

        self.name_edit = q.QLineEdit()
        self.form.addRow('&Name:', self.name_edit)
        self.mapper.addMapping(self.name_edit, ActorModelColumn.Name)

        self.sub_name_edit = q.QLineEdit()
        self.form.addRow('S&ub name:', self.sub_name_edit)
        self.mapper.addMapping(self.sub_name_edit, ActorModelColumn.SubName)

        self.arg_group = self.createArgumentGroup()
        model = self.mapper.model()
        ep = model.data(model.createIndex(idx, -1), qc.Qt.UserRole).argument_entry_point.v
        if ep:
            self.arg_group.setChecked(True)
            self.ep_cbox.setCurrentIndex(self.ep_cbox.model().l.index(ep))
        else:
            self.arg_group.setChecked(False)

        self.btn_box = q.QDialogButtonBox(q.QDialogButtonBox.Save | q.QDialogButtonBox.Cancel);

    def createArgumentGroup(self) -> q.QGroupBox:
        form = q.QFormLayout()

        self.argument_name_edit = q.QLineEdit()
        form.addRow('Argument name:', self.argument_name_edit)
        self.mapper.addMapping(self.argument_name_edit, ActorModelColumn.ArgumentName)

        self.ep_cbox = q.QComboBox()
        form.addRow('Entry point:', self.ep_cbox)
        self.ep_cbox.setModel(self.flow_data.entry_point_model)
        self.mapper.addMapping(self.ep_cbox, ActorModelColumn.ArgumentEntryPoint, b'currentData')

        group = q.QGroupBox('Is an &argument')
        group.setCheckable(True)
        group.setLayout(form)
        return group

    def initLayout(self) -> None:
        layout = q.QVBoxLayout(self)
        layout.addLayout(self.form)
        layout.addWidget(self.arg_group)
        layout.addWidget(self.btn_box)

    def connectWidgets(self) -> None:
        self.btn_box.accepted.connect(self.accept)
        self.btn_box.rejected.connect(self.reject)

    def accept(self) -> None:
        model = self.mapper.model()
        identifier = ActorIdentifier(self.name_edit.text(), self.sub_name_edit.text())
        if identifier != self.prev_identifier and model.has(identifier):
            q.QMessageBox.critical(self, 'Cannot edit actor', f'{identifier} is already used as an actor identifier. Please pick another one.')
            return

        self.mapper.submit()
        if not self.arg_group.isChecked():
            model.setData(model.createIndex(self.mapper.currentIndex(), ActorModelColumn.ArgumentName), '', qc.Qt.EditRole)
            model.setData(model.createIndex(self.mapper.currentIndex(), ActorModelColumn.ArgumentEntryPoint), None, qc.Qt.EditRole)
        super().accept()

class ActorAddDialog(ActorEditDialog):
    def __init__(self, parent, flow_data, idx) -> None:
        super().__init__(parent, flow_data, idx)
        self.setWindowTitle('Add new actor')

    def reject(self) -> None:
        self.flow_data.actor_model.remove(self.flow_data.actor_model.data(
            self.flow_data.actor_model.createIndex(self.flow_data.actor_model.rowCount(None) - 1, -1),
            qc.Qt.UserRole))
        super().reject()

class ActorDetailPane(q.QWidget):
    jumpToEventsRequested = qc.pyqtSignal(str)

    def __init__(self, parent, flow_data) -> None:
        super().__init__(parent)
        self.flow_data = flow_data
        self.actor: typing.Optional[Actor] = None
        self.action_model = ActorStringListModel(parent, [])
        self.query_model = ActorStringListModel(parent, [])
        self.container_model = ContainerModel(parent)
        self.initWidgets()
        self.initLayout()
        self.connectWidgets()

    def setActor(self, actor: typing.Optional[Actor]) -> None:
        self.actor = actor
        self.action_model.set(self.actor.actions if self.actor else [])
        self.query_model.set(self.actor.queries if self.actor else [])
        if self.actor and not self.actor.params:
            self.actor.params = Container()
        self.container_model.set(self.actor.params if self.actor else None)
        if self.actor:
            self.action_view.setActor(self.actor)
            self.query_view.setActor(self.actor)

    def initWidgets(self) -> None:
        self.action_view = ActorActionListView(self, self.action_model, self.flow_data)
        self.query_view = ActorQueryListView(self, self.query_model, self.flow_data)
        self.container_view = ContainerView(self, self.container_model, self.flow_data)
        self.copy_xml_btn = self.container_view.addHeaderButton('Copy', self.copyParametersXml)
        self.paste_xml_btn = self.container_view.addHeaderButton('Paste', self.pasteParametersXml)
        self.import_xml_btn = self.container_view.addHeaderButton('Import...', self.importParametersXml)
        self.export_xml_btn = self.container_view.addHeaderButton('Export...', self.exportParametersXml)

    def initLayout(self) -> None:
        layout = q.QHBoxLayout(self)

        layout.addWidget(self.action_view, stretch=1)
        layout.addWidget(self.query_view, stretch=1)
        layout.addWidget(self.container_view, stretch=2)
        layout.setContentsMargins(0, 0, 0, 0)

    def connectWidgets(self) -> None:
        util.connect_model_change_signals(self.action_model, self.flow_data, FlowDataChangeReason.Actors)
        util.connect_model_change_signals(self.query_model, self.flow_data, FlowDataChangeReason.Actors)
        util.connect_model_change_signals(self.container_model, self.flow_data, FlowDataChangeReason.Actors)

        self.action_view.addActionBuilder(lambda menu, idx: menu.addAction('&Jump to events', lambda: self.onJumpToEvents(idx)))
        self.query_view.addActionBuilder(lambda menu, idx: menu.addAction('&Jump to events', lambda: self.onJumpToEvents(idx)))
        self.container_view.addActionBuilder(lambda menu, idx: menu.addAction('&Add default create parameters', lambda: self.addDefaultCreateParameters()))

    def addDefaultCreateParameters(self) -> None:
        if not self.actor or not self.actor.params:
            return
        self.actor.params.data.update({'CreateMode': 0, 'IsGrounding': False, 'IsWorld': False, 'PosX': 0.0, 'PosY': 0.0, 'PosZ': 0.0, 'RotX': 0.0, 'RotY': 0.0, 'RotZ': 0.0})
        self.container_model.set(self.actor.params)

    def _ensureActorParams(self) -> typing.Optional[Container]:
        if not self.actor:
            return None
        if not self.actor.params:
            self.actor.params = Container()
            self.container_model.set(self.actor.params)
        return self.actor.params

    def _replaceActorParams(self, data: typing.Dict[str, typing.Any]) -> None:
        params = self._ensureActorParams()
        if not params:
            return
        params.data.clear()
        params.data.update(data)
        self.container_model.set(params)
        self.flow_data.flowDataChanged.emit(FlowDataChangeReason.Actors)

    def copyParametersXml(self) -> None:
        params = self._ensureActorParams()
        if not params:
            return
        q.QApplication.clipboard().setText(cxml.dumps_container_dict(params.data))

    def pasteParametersXml(self) -> None:
        try:
            data = cxml.loads_container_dict(q.QApplication.clipboard().text())
        except Exception as exc:
            q.QMessageBox.critical(self, 'Paste XML', f'Failed to parse clipboard XML.\n\n{exc}')
            return
        self._replaceActorParams(data)

    def importParametersXml(self) -> None:
        if not self.actor:
            return
        default_name = f'{self.actor.identifier.name or "actor"}_params.xml'
        path = q.QFileDialog.getOpenFileName(self, 'Import actor parameters from XML...', default_name, 'XML (*.xml)')[0]
        if not path:
            return
        try:
            with open(path, 'rt', encoding='utf-8') as file:
                data = cxml.loads_container_dict(file.read())
        except Exception as exc:
            q.QMessageBox.critical(self, 'Import XML', f'Failed to import actor parameters.\n\n{exc}')
            return
        self._replaceActorParams(data)

    def exportParametersXml(self) -> None:
        params = self._ensureActorParams()
        if not params or not self.actor:
            return
        default_name = f'{self.actor.identifier.name or "actor"}_params.xml'
        path = q.QFileDialog.getSaveFileName(self, 'Export actor parameters to XML...', default_name, 'XML (*.xml)')[0]
        if not path:
            return
        try:
            with open(path, 'wt', encoding='utf-8') as file:
                file.write(cxml.dumps_container_dict(params.data))
        except Exception as exc:
            q.QMessageBox.critical(self, 'Export XML', f'Failed to export actor parameters.\n\n{exc}')

    def onJumpToEvents(self, idx) -> None:
        if self.actor:
            self.jumpToEventsRequested.emit(f'{self.actor.identifier}::{idx.data(qc.Qt.UserRole)}')

class ActorView(q.QWidget):
    jumpToActorEventsRequested = qc.pyqtSignal(str)

    def __init__(self, parent, flow_data) -> None:
        super().__init__(parent)
        self.flow_data = flow_data
        self.actor_sort_column: typing.Optional[int] = None
        self.actor_sort_order = qc.Qt.AscendingOrder
        self.initWidgets()
        self.initLayout()
        self.connectWidgets()

    def initWidgets(self) -> None:
        self.actor_proxy_model = SortableHeaderProxyModel(self)
        self.actor_proxy_model.setSourceModel(self.flow_data.actor_model)
        self.actor_proxy_model.setSortCaseSensitivity(qc.Qt.CaseInsensitive)
        self.actor_proxy_model.setDynamicSortFilter(True)

        self.actor_view = q.QTableView()
        self.actor_view.setModel(self.actor_proxy_model)
        self.actor_view.verticalHeader().hide()
        self.actor_view.setSelectionBehavior(q.QAbstractItemView.SelectRows)
        self.actor_view.setSelectionMode(q.QAbstractItemView.ExtendedSelection)
        self.actor_view.horizontalHeader().setSectionResizeMode(q.QHeaderView.ResizeToContents)
        self.actor_view.horizontalHeader().setSectionResizeMode(0, q.QHeaderView.Stretch)
        self.actor_view.horizontalHeader().setSectionResizeMode(1, q.QHeaderView.Stretch)
        self.actor_view.horizontalHeader().setSectionsClickable(True)
        self.actor_view.horizontalHeader().setSortIndicatorShown(False)
        self.actor_view.setEditTriggers(q.QAbstractItemView.NoEditTriggers);
        self.actor_view.setContextMenuPolicy(qc.Qt.CustomContextMenu)
        self.actor_view.customContextMenuRequested.connect(self.onContextMenu)

        self.detail_pane = ActorDetailPane(None, self.flow_data)

        self.top_box = q.QHBoxLayout()
        self.top_box.setContentsMargins(5,5,5,0)
        self.num_actors_label = q.QLabel()
        self.top_box.addWidget(self.num_actors_label, stretch=1)
        self.add_actor_btn = q.QPushButton('A&dd...')
        self.add_actor_btn.setEnabled(False)
        self.top_box.addWidget(self.add_actor_btn)

    def initLayout(self) -> None:
        splitter = q.QSplitter(qc.Qt.Vertical)
        splitter.addWidget(self.actor_view)
        self.stacked_pane = q.QStackedWidget()
        self.stacked_pane.addWidget(q.QWidget())
        self.stacked_pane.addWidget(self.detail_pane)
        splitter.addWidget(self.stacked_pane)
        splitter.setSizes([int(splitter.height() * 0.6), int(splitter.height() * 0.4)])
        layout = q.QVBoxLayout(self)
        layout.addLayout(self.top_box)
        layout.addWidget(splitter, stretch=1)
        layout.setContentsMargins(0, 0, 0, 0)

    def connectWidgets(self) -> None:
        self.add_actor_btn.clicked.connect(self.addActor)
        self.flow_data.fileLoaded.connect(lambda: self.add_actor_btn.setEnabled(True))
        self.flow_data.fileLoaded.connect(lambda: self.hideActorDetailPane())
        self.flow_data.flowDataChanged.connect(self.updateNumActorLabel)
        self.updateNumActorLabel()

        self.actor_view.doubleClicked.connect(self.editActor)
        self.actor_view.selectionModel().currentRowChanged.connect(self.onCurrentChanged)
        self.actor_view.selectionModel().selectionChanged.connect(self.onSelectionChanged)
        self.actor_view.horizontalHeader().sectionClicked.connect(self.onActorHeaderClicked)

    def updateNumActorLabel(self, *_) -> None:
        self.num_actors_label.setText(f'{self.flow_data.actor_model.rowCount(None)} actor(s)')

    def addActor(self) -> None:
        ok = self.flow_data.actor_model.appendEmptyActor()
        assert ok
        dialog = ActorAddDialog(self, self.flow_data, self.flow_data.actor_model.rowCount(None) - 1)
        dialog.exec_()

    def editActor(self, idx: qc.QModelIndex) -> None:
        source_idx = self._mapActorIndexToSource(idx)
        if not source_idx.isValid():
            return
        dialog = ActorEditDialog(self, self.flow_data, source_idx.row())
        dialog.exec_()

    def removeActor(self, idx: qc.QModelIndex) -> None:
        source_idx = self._mapActorIndexToSource(idx)
        if not source_idx.isValid():
            return
        actor = source_idx.data(qc.Qt.UserRole)
        if util.is_actor_in_use(self.flow_data.flow.flowchart.events, actor):
            q.QMessageBox.critical(self, 'Cannot delete actor', f'{actor.identifier} cannot be deleted because it is used by events. Please remove any references to this actor and try again.')
            return

        self.flow_data.actor_model.remove(actor)

    def hideActorDetailPane(self) -> None:
        self.detail_pane.setActor(None)
        self.stacked_pane.setCurrentIndex(0)

    def _getSelectedRows(self) -> typing.List[qc.QModelIndex]:
        smodel = self.actor_view.selectionModel()
        if not smodel:
            return []
        rows: typing.List[qc.QModelIndex] = []
        for index in smodel.selectedRows():
            source_index = self._mapActorIndexToSource(index)
            if source_index.isValid():
                rows.append(source_index)
        return rows

    def _mapActorIndexToSource(self, index: qc.QModelIndex) -> qc.QModelIndex:
        if not index.isValid():
            return qc.QModelIndex()
        if index.model() is self.actor_proxy_model:
            return self.actor_proxy_model.mapToSource(index)
        return index

    def onActorHeaderClicked(self, section: int) -> None:
        if self.actor_sort_column == section and self.actor_sort_order == qc.Qt.AscendingOrder:
            self.actor_sort_order = qc.Qt.DescendingOrder
        else:
            self.actor_sort_column = section
            self.actor_sort_order = qc.Qt.AscendingOrder

        header = self.actor_view.horizontalHeader()
        header.setSortIndicator(section, self.actor_sort_order)
        header.setSortIndicatorShown(True)
        self.actor_proxy_model.setSortDescriptor(section, 'Z-A' if self.actor_sort_order == qc.Qt.DescendingOrder else 'A-Z')
        self.actor_proxy_model.sort(section, self.actor_sort_order)

    def _getSelectedActors(self) -> typing.List[Actor]:
        return [idx.data(qc.Qt.UserRole) for idx in self._getSelectedRows()]

    def _serializeActor(self, actor: Actor) -> typing.Dict[str, typing.Any]:
        return {
            'name': actor.identifier.name,
            'sub_name': actor.identifier.sub_name,
            'argument_name': actor.argument_name,
            'argument_entry_point': actor.argument_entry_point.v.name if actor.argument_entry_point.v else None,
            'concurrent_clips': actor.concurrent_clips,
            'actions': [action.v for action in actor.actions],
            'queries': [query.v for query in actor.queries],
            'params': dict(actor.params.data) if actor.params else None,
        }

    def _makeUniqueIdentifierName(self, name: str, sub_name: str, used_identifiers: typing.Set[typing.Tuple[str, str]]) -> str:
        base_name = name or 'Actor'
        candidate_name = base_name
        suffix = 1
        while (candidate_name, sub_name) in used_identifiers:
            candidate_name = f'{base_name} ({suffix})'
            suffix += 1
        used_identifiers.add((candidate_name, sub_name))
        return candidate_name

    def _buildActorFromPayload(self, payload: typing.Dict[str, typing.Any],
                               used_identifiers: typing.Set[typing.Tuple[str, str]]) -> Actor:
        actor = Actor()
        actor.identifier.name = self._makeUniqueIdentifierName(payload.get('name', ''), payload.get('sub_name', ''), used_identifiers)
        actor.identifier.sub_name = payload.get('sub_name', '')
        actor.argument_name = payload.get('argument_name', '')
        actor.concurrent_clips = int(payload.get('concurrent_clips', 0xFFFF))
        actor.actions = [StringHolder(action) for action in payload.get('actions', [])]
        actor.queries = [StringHolder(query) for query in payload.get('queries', [])]
        params = payload.get('params')
        if params is not None:
            actor.params = Container()
            actor.params.data = dict(params)
        entry_point_name = payload.get('argument_entry_point')
        if entry_point_name and self.flow_data.flow and self.flow_data.flow.flowchart:
            entry_point = next((ep for ep in self.flow_data.flow.flowchart.entry_points if ep.name == entry_point_name), None)
            actor.argument_entry_point.v = entry_point
        return actor

    def _appendActorsFromPayloads(self, payloads: typing.Iterable[typing.Dict[str, typing.Any]]) -> None:
        used_identifiers = {(actor.identifier.name, actor.identifier.sub_name) for actor in self.flow_data.actor_model.l}
        added = False
        for payload in payloads:
            actor = self._buildActorFromPayload(payload, used_identifiers)
            if self.flow_data.actor_model.appendActor(actor):
                added = True
        if added:
            self.actor_view.clearSelection()

    def copyActors(self) -> None:
        actors = self._getSelectedActors()
        if not actors:
            return
        q.QApplication.clipboard().setText(axml.dumps_actors(self._serializeActor(actor) for actor in actors))

    def pasteActors(self) -> None:
        try:
            payloads = axml.loads_actors(q.QApplication.clipboard().text())
        except Exception as exc:
            q.QMessageBox.critical(self, 'Paste actors', f'Failed to paste actors.\n\n{exc}')
            return
        if not payloads:
            return
        self._appendActorsFromPayloads(payloads)

    def exportActorsXml(self) -> None:
        actors = self._getSelectedActors()
        if not actors:
            return
        default_name = f'{actors[0].identifier.name or "actors"}.actors.xml' if len(actors) == 1 else 'actors.xml'
        path = q.QFileDialog.getSaveFileName(self, 'Export actors...', default_name, 'XML (*.xml)')[0]
        if not path:
            return
        try:
            with open(path, 'wt', encoding='utf-8') as file:
                file.write(axml.dumps_actors(self._serializeActor(actor) for actor in actors))
        except Exception as exc:
            q.QMessageBox.critical(self, 'Export actors', f'Failed to export actors.\n\n{exc}')

    def importActorsXml(self) -> None:
        path = q.QFileDialog.getOpenFileName(self, 'Import actors...', 'actors.xml', 'XML (*.xml)')[0]
        if not path:
            return
        try:
            with open(path, 'rt', encoding='utf-8') as file:
                payloads = axml.loads_actors(file.read())
        except Exception as exc:
            q.QMessageBox.critical(self, 'Import actors', f'Failed to import actors.\n\n{exc}')
            return
        self._appendActorsFromPayloads(payloads)

    def deleteSelectedActors(self) -> None:
        rows = self._getSelectedRows()
        if not rows:
            return
        selected_actors = [idx.data(qc.Qt.UserRole) for idx in rows]
        blocked_identifiers: typing.List[str] = []
        deletable_actors: typing.List[Actor] = []
        for actor in selected_actors:
            if util.is_actor_in_use(self.flow_data.flow.flowchart.events, actor):
                blocked_identifiers.append(str(actor.identifier))
            else:
                deletable_actors.append(actor)

        for actor in deletable_actors:
            self.flow_data.actor_model.remove(actor)

        if blocked_identifiers:
            q.QMessageBox.critical(
                self,
                'Cannot delete actor',
                'Some selected actors cannot be deleted because they are used by events:\n\n' +
                '\n'.join(blocked_identifiers[:20])
            )

    def onCurrentChanged(self, current, previous) -> None:
        if previous.row() == -1:
            self.hideActorDetailPane()

    def onSelectionChanged(self, selected, deselected) -> None:
        selected_rows = self._getSelectedRows()
        if len(selected_rows) != 1:
            self.hideActorDetailPane()
            return

        self.detail_pane.setActor(selected_rows[0].data(qc.Qt.UserRole))
        self.stacked_pane.setCurrentIndex(1)

    def onContextMenu(self, pos) -> None:
        smodel = self.actor_view.selectionModel()
        index = self.actor_view.indexAt(pos)
        if index.isValid() and not smodel.isRowSelected(index.row(), qc.QModelIndex()):
            smodel.clearSelection()
            self.actor_view.selectRow(index.row())

        selected_rows = self._getSelectedRows()
        selected_count = len(selected_rows)
        idx = selected_rows[0] if selected_rows else None

        menu = q.QMenu()
        if selected_count == 1 and idx is not None:
            menu.addAction('&Edit...', lambda: self.editActor(idx))
            menu.addAction('&Jump to events', lambda: self.jumpToActorEventsRequested.emit(str(idx.data(qc.Qt.UserRole).identifier) + '::'))
            menu.addSeparator()
        if selected_count:
            menu.addAction('&Copy', self.copyActors)
        menu.addAction('&Paste', self.pasteActors)
        menu.addAction('E&xport...', self.exportActorsXml)
        menu.addAction('&Import...', self.importActorsXml)
        if selected_count:
            menu.addSeparator()
        if selected_count == 1 and idx is not None:
            menu.addAction('&Delete', lambda: self.removeActor(idx))
        else:
            if selected_count > 1:
                menu.addAction(f'&Delete selected ({selected_count})', self.deleteSelectedActors)
        menu.exec_(self.sender().viewport().mapToGlobal(pos))
