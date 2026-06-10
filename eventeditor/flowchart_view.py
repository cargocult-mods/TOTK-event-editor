import base64
import copy
import json
import pickle
from pathlib import Path
import traceback
import typing

import eventeditor.actor_json as aj
from eventeditor.container_model import ContainerModel
from eventeditor.container_view import ContainerView
import eventeditor.entry_point_tree_xml as eptxml
from eventeditor.event_branch_editors import SwitchEventEditDialog, ForkEventEditDialog
from eventeditor.event_edit_dialog import show_event_editor
from eventeditor.event_chooser_dialog import show_event_type_chooser, add_new_event, EventChooserDialog, CheckableEventParentListWidget
from eventeditor.event_fork_chooser_dialog import EventForkChooserDialog
from eventeditor.flow_data import FlowData, FlowDataChangeReason
from eventeditor.entry_point_model import EntryPointModel
import eventeditor.flowchart_tools as ft
import eventeditor.mals as mals
from eventeditor.search_bar import SearchBar
from eventeditor.util import *
from evfl import Container, Flowchart, Actor, Event, EventFlow, ActionEvent, SwitchEvent, ForkEvent, JoinEvent, SubFlowEvent
from evfl.common import Index, RequiredIndex, StringHolder
from evfl.entry_point import EntryPoint
from evfl.enums import EventType
from evfl.repr_util import generate_flowchart_graph
from PyQt5.QtWebChannel import QWebChannel # type: ignore
from PyQt5.QtWebEngineWidgets import QWebEngineView # type: ignore
import PyQt5.QtCore as qc # type: ignore
import PyQt5.QtGui as qg # type: ignore
import PyQt5.QtWidgets as q # type: ignore

EVENT_CLIPBOARD_PREFIX = 'eventeditor-event-nodes:v1:'

class EntryPointVisibilityDelegate(q.QStyledItemDelegate):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._pressed_on_icon = False

    def _iconRect(self, option: q.QStyleOptionViewItem) -> qc.QRect:
        icon_size = option.decorationSize if option.decorationSize.isValid() else qc.QSize(18, 18)
        x = option.rect.left() + 4
        y = option.rect.top() + max(0, (option.rect.height() - icon_size.height()) // 2)
        return qc.QRect(qc.QPoint(x, y), icon_size)

    def editorEvent(self, event, model, option, index) -> bool:
        if event.type() == qc.QEvent.MouseButtonPress:
            self._pressed_on_icon = self._iconRect(option).contains(event.pos())
            if self._pressed_on_icon:
                return True
        elif event.type() == qc.QEvent.MouseButtonDblClick:
            if self._iconRect(option).contains(event.pos()):
                return True
        elif event.type() == qc.QEvent.MouseButtonRelease:
            on_icon = self._iconRect(option).contains(event.pos())
            if self._pressed_on_icon and on_icon:
                self._pressed_on_icon = False
                return bool(model.setData(index, not bool(index.data(EntryPointModel.HiddenRole)), EntryPointModel.HiddenRole))
            self._pressed_on_icon = False
        return super().editorEvent(event, model, option, index)

class FlowNameLabel(q.QLabel):
    doubleClicked = qc.pyqtSignal()

    def contextMenuEvent(self, event) -> None:
        menu = q.QMenu(self)
        menu.addAction('Edit', lambda checked=False: self.doubleClicked.emit())
        menu.exec_(event.globalPos())
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == qc.Qt.LeftButton:
            self.doubleClicked.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

class FlowchartWebObject(qc.QObject):
    flowDataChanged = qc.pyqtSignal()
    fileLoaded = qc.pyqtSignal(EventFlow)
    eventNameVisibilityChanged = qc.pyqtSignal(bool)
    eventParamVisibilityChanged = qc.pyqtSignal(bool)
    eventMessageVisibilityChanged = qc.pyqtSignal(bool)
    eventTagVisibilityChanged = qc.pyqtSignal(bool)
    entryPointFilterStateChanged = qc.pyqtSignal(bool)
    fastGraphReloadRequested = qc.pyqtSignal()
    actionProhibitionChanged = qc.pyqtSignal(bool)
    preserveViewportRequested = qc.pyqtSignal()
    revealRequested = qc.pyqtSignal(int)
    instantRevealRequested = qc.pyqtSignal(int)

    selectRequested = qc.pyqtSignal(int)

    def __init__(self, view) -> None:
        super().__init__(view)
        self.view: FlowchartView = view

    @qc.pyqtSlot(result=qc.QVariant)
    def getJson(self) -> qc.QVariant:
        return qc.QVariant(json.loads(json.dumps(self.getData(), default=lambda x: str(x))))

    def getData(self) -> list:
        return self.view.getGraphData()

    @qc.pyqtSlot()
    def emitReadySignal(self):
        self.view.readySignal.emit()

    @qc.pyqtSlot(int)
    def emitEventSelectedSignal(self, node_id: int) -> None:
        self.view.eventSelected.emit(int(node_id))

    @qc.pyqtSlot(list)
    def emitSelectedNodeIdsSignal(self, node_ids: typing.List[typing.Any]) -> None:
        self.view.selectedNodeIdsChanged.emit([int(x) for x in node_ids])

    @qc.pyqtSlot()
    def emitReloadedSignal(self):
        self.view.reloadedSignal.emit()

    @qc.pyqtSlot(int, int)
    def emitSearchResultsSignal(self, count: int, index: int) -> None:
        self.view.onGraphSearchResultsChanged(int(count), int(index))

    @qc.pyqtSlot(int)
    def editEvent(self, node_id: int):
        self.view.webEditEvent(int(node_id))

    @qc.pyqtSlot(int)
    def addEntryPoint(self, node_id: int):
        self.view.webAddEntryPoint(int(node_id))

    @qc.pyqtSlot(int)
    def removeEntryPoint(self, node_id: int):
        self.view.webRemoveEntryPoint(-1000-int(node_id))

    @qc.pyqtSlot(list, int)
    def addEventAbove(self, parents: typing.List[int], node_id: int):
        self.view.webAddEventAbove([int(x) for x in parents], int(node_id))

    @qc.pyqtSlot(int)
    def addEventBelow(self, node_id: int):
        self.view.webAddEventBelow(int(node_id))

    @qc.pyqtSlot(int)
    def unlink(self, node_id: int):
        self.view.webUnlink(int(node_id))

    @qc.pyqtSlot(int)
    def link(self, node_id: int):
        self.view.webLink(int(node_id))

    @qc.pyqtSlot(list, int)
    def removeEvent(self, parents: typing.List[int], node_id: int):
        self.view.webRemoveEvent([int(x) for x in parents], int(node_id))

    @qc.pyqtSlot(int)
    def editSwitchBranches(self, node_id: int):
        self.view.webEditSwitchBranches(int(node_id))

    @qc.pyqtSlot(int)
    def editForkBranches(self, node_id: int):
        self.view.webEditForkBranches(int(node_id))

    @qc.pyqtSlot(list)
    def copyEvents(self, node_ids: typing.List[int]):
        self.view.webCopyEvents([int(x) for x in node_ids])

    @qc.pyqtSlot()
    def pasteEvents(self):
        self.view.webPasteEvents(reveal_new_events=True)

    @qc.pyqtSlot(int)
    def pasteEventsInto(self, node_id: int):
        self.view.webPasteEvents(target_idx=int(node_id), reveal_new_events=False)

    @qc.pyqtSlot(list)
    def removeEvents(self, node_ids: typing.List[int]):
        self.view.webRemoveEvents([int(x) for x in node_ids])

    @qc.pyqtSlot()
    def addStandaloneEvent(self):
        self.view.addNewEvent()

    @qc.pyqtSlot()
    def addFork(self):
        self.view.addFork()

    @qc.pyqtSlot(int)
    def addForkAt(self, node_id: int):
        self.view.addFork(node_id=int(node_id))

    @qc.pyqtSlot(int)
    def addEntryPointChild(self, node_id: int):
        self.view.webAddEntryPointChild(int(node_id))

    @qc.pyqtSlot(int)
    def renameEntryPoint(self, node_id: int):
        self.view.webRenameEntryPoint(int(node_id))

    @qc.pyqtSlot(int)
    def showOnlyConnectedEvents(self, node_id: int):
        self.view.webShowOnlyConnectedEvents(int(node_id))

    @qc.pyqtSlot(int)
    def goToSubflowEntryPoint(self, node_id: int):
        self.view.webGoToSubflowEntryPoint(int(node_id))

    @qc.pyqtSlot()
    def showAllEvents(self):
        self.view.webShowAllEvents()

    @qc.pyqtSlot(int)
    def showAllEventsFromNode(self, node_id: int):
        self.view.webShowAllEvents(int(node_id))

class FlowchartView(q.QWidget):
    selectRequested = qc.pyqtSignal(int)
    eventNameVisibilityChanged = qc.pyqtSignal(bool)
    eventParamVisibilityChanged = qc.pyqtSignal(bool)
    eventMessageVisibilityChanged = qc.pyqtSignal(bool)
    eventTagVisibilityChanged = qc.pyqtSignal(bool)

    # View -> Core
    readySignal = qc.pyqtSignal()
    reloadedSignal = qc.pyqtSignal()
    eventSelected = qc.pyqtSignal(int)
    selectedNodeIdsChanged = qc.pyqtSignal(list)
    externalSubflowOpenRequested = qc.pyqtSignal(str, str)

    def __init__(self, parent, flow_data: FlowData) -> None:
        super().__init__(parent)
        self.flow_data: FlowData = flow_data
        self.is_current = True
        self.selected_event: typing.Optional[Event] = None
        self.selected_node_id: typing.Optional[int] = None
        self.pending_reveal_event: typing.Optional[Event] = None
        self.pending_reveal_node_id: typing.Optional[int] = None
        self.pending_reveal_duration_ms: typing.Optional[int] = None
        self.suppress_reload_reselect = False
        self.showEventParams = False
        self.showEventMessages = False
        self.showMessageTags = True
        self.renderMessageTagsAsStyling = True
        self.showNonTextMessageTags = True
        self.includeMessageBlankLines = True
        self.showMessageBubbleBreaks = True
        self.dark_mode = False
        self._open_dialogs: typing.List[q.QDialog] = []
        self._entry_point_reachable_cache_key: typing.Optional[typing.Tuple[int, int, int]] = None
        self._entry_point_reachable_cache: typing.List[typing.Set[Event]] = []
        self._message_archive_path = ''
        self._message_archive_missing_text = ''
        self._message_lookup_key: typing.Tuple[str, typing.FrozenSet[str], bool, str] = ('', frozenset(), True, '')
        self._message_lookup: typing.Dict[str, str] = {}
        self.initWidgets()
        self.initLayout()
        self.connectWidgets()

    def initWidgets(self) -> None:
        self.web_object = FlowchartWebObject(self)
        self.flow_data.flowDataChanged.connect(self.onFlowDataChanged)
        self.flow_data.fileLoaded.connect(lambda flow: self._invalidateEntryPointReachabilityCache())
        self.flow_data.fileLoaded.connect(self.web_object.fileLoaded)
        self.selectRequested.connect(self.web_object.selectRequested)
        self.eventNameVisibilityChanged.connect(self.web_object.eventNameVisibilityChanged)
        self.eventParamVisibilityChanged.connect(self.onEventParamVisibilityChanged)
        self.eventParamVisibilityChanged.connect(self.web_object.eventParamVisibilityChanged)
        self.eventMessageVisibilityChanged.connect(self.onEventMessageVisibilityChanged)
        self.eventMessageVisibilityChanged.connect(self.web_object.eventMessageVisibilityChanged)
        self.eventTagVisibilityChanged.connect(self.onEventTagVisibilityChanged)
        self.eventTagVisibilityChanged.connect(self.web_object.eventTagVisibilityChanged)

        self.view = QWebEngineView()
        self.view.setContextMenuPolicy(qc.Qt.NoContextMenu)
        self.channel = QWebChannel()
        self.channel.registerObject('widget', self.web_object)
        self.view.page().setWebChannel(self.channel)
        self.view.page().setBackgroundColor(qg.QColor(0x38, 0x38, 0x38));
        self.view.setUrl(qc.QUrl.fromLocalFile(get_path('assets/index.html')))

        self.entry_point_view = q.QListView(self)
        self.flow_name_label = FlowNameLabel(self)
        self.flow_name_label.setTextInteractionFlags(qc.Qt.TextSelectableByMouse)
        flow_name_font = self.flow_name_label.font()
        flow_name_font.setBold(True)
        self.flow_name_label.setFont(flow_name_font)
        self.flow_name_label.setContentsMargins(6, 4, 6, 2)
        self.flow_name_label.setVisible(False)
        self.ep_proxy_model = qc.QSortFilterProxyModel(self)
        self.ep_proxy_model.setSourceModel(self.flow_data.entry_point_model)
        self.ep_proxy_model.setFilterKeyColumn(-1)
        self.entry_point_view.setModel(self.ep_proxy_model)
        self.entry_point_view.setIconSize(qc.QSize(18, 18))
        self.entry_point_view.setSelectionMode(q.QAbstractItemView.ExtendedSelection)
        self.entry_point_view.setContextMenuPolicy(qc.Qt.CustomContextMenu)
        self.entry_point_view.setItemDelegate(EntryPointVisibilityDelegate(self.entry_point_view))

        visible_icon = qg.QIcon(get_path('assets/material_visibility_24.svg'))
        hidden_icon = qg.QIcon(get_path('assets/material_visibility_off_24.svg'))
        self.flow_data.entry_point_model.setVisibilityIcons(visible_icon, hidden_icon)
        self.ep_search = SearchBar()
        self.ep_search.hide()

        self.container_model = ContainerModel(self)
        self.container_view = ContainerView(None, self.container_model, self.flow_data)
        self.container_stacked_widget = q.QStackedWidget()
        self.container_stacked_widget.addWidget(q.QWidget())
        self.container_stacked_widget.addWidget(self.container_view)

        self.update_timer = qc.QTimer(self)
        self.update_timer.timeout.connect(self.web_object.flowDataChanged)
        self.update_timer.setSingleShot(True)

        self.graph_search_edit = q.QLineEdit(self)
        self.graph_search_edit.setPlaceholderText('Search text...')
        self.graph_search_scope_combo = q.QComboBox(self)
        for label, value in (
            ('All', 'all'),
            ('Text', 'mals'),
            ('Parameters', 'params'),
            ('Events', 'events'),
            ('Switches', 'switches'),
            ('Subflows', 'subflows'),
        ):
            self.graph_search_scope_combo.addItem(label, value)
        self.graph_search_prev_button = q.QToolButton(self)
        self.graph_search_prev_button.setText('Prev')
        self.graph_search_next_button = q.QToolButton(self)
        self.graph_search_next_button.setText('Next')
        self.graph_search_index_edit = q.QLineEdit(self)
        self.graph_search_index_edit.setAlignment(qc.Qt.AlignRight | qc.Qt.AlignVCenter)
        self.graph_search_index_edit.setMaxLength(6)
        self.graph_search_index_edit.setFrame(False)
        self.graph_search_index_edit.setStyleSheet(
            'QLineEdit { background: transparent; border: none; padding: 0 1px 0 0; margin: 0; min-height: 0px; }'
        )
        self.graph_search_index_edit.setTextMargins(0, 0, 0, 0)
        self.graph_search_index_edit.setFixedWidth(12)
        self.graph_search_index_edit.setSizePolicy(q.QSizePolicy.Fixed, q.QSizePolicy.Fixed)
        self.graph_search_index_edit.setValidator(qg.QIntValidator(1, 999999, self.graph_search_index_edit))
        self.graph_search_index_edit.setFont(self.font())
        self.graph_search_total_label = q.QLabel('/0', self)
        self.graph_search_total_label.setMinimumWidth(0)
        self.graph_search_total_label.setStyleSheet('QLabel { padding: 0; margin: 0; }')
        self.graph_search_total_label.setSizePolicy(q.QSizePolicy.Fixed, q.QSizePolicy.Fixed)
        self.graph_search_total_label.setFont(self.font())
        search_counter_height = max(
            self.graph_search_index_edit.sizeHint().height(),
            self.graph_search_total_label.sizeHint().height(),
        )
        self.graph_search_index_edit.setFixedHeight(search_counter_height)
        self.graph_search_total_label.setFixedHeight(search_counter_height)
        self.graph_search_case_checkbox = q.QCheckBox('Case insensitive', self)
        self.graph_search_case_checkbox.setChecked(True)

    def initLayout(self) -> None:
        left_pane_splitter = q.QSplitter(qc.Qt.Vertical)
        ep_widget = q.QWidget()
        ep_layout = q.QVBoxLayout(ep_widget)
        ep_layout.setContentsMargins(0, 0, 0, 0)
        ep_layout.addWidget(self.flow_name_label)
        ep_layout.addWidget(self.entry_point_view, stretch=1)
        ep_layout.addWidget(self.ep_search)
        left_pane_splitter.addWidget(ep_widget)
        left_pane_splitter.addWidget(self.container_stacked_widget)
        left_pane_splitter.setSizes([int(left_pane_splitter.height() * 0.6), int(left_pane_splitter.height() * 0.4)])

        right_widget = q.QWidget(self)
        right_layout = q.QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        search_layout = q.QHBoxLayout()
        search_layout.setContentsMargins(4, 4, 4, 0)
        search_layout.setSpacing(4)
        search_layout.addWidget(self.graph_search_scope_combo)
        search_layout.addWidget(self.graph_search_edit, stretch=1)
        search_layout.addWidget(self.graph_search_prev_button)
        search_layout.addWidget(self.graph_search_next_button)
        graph_search_result_widget = q.QWidget(self)
        graph_search_result_layout = q.QHBoxLayout(graph_search_result_widget)
        graph_search_result_layout.setContentsMargins(0, 0, 0, 0)
        graph_search_result_layout.setSpacing(0)
        graph_search_result_layout.setAlignment(qc.Qt.AlignVCenter)
        graph_search_result_layout.addWidget(self.graph_search_index_edit)
        graph_search_result_layout.addWidget(self.graph_search_total_label)
        search_layout.addWidget(graph_search_result_widget)
        search_layout.addWidget(self.graph_search_case_checkbox)
        right_layout.addLayout(search_layout)
        right_layout.addWidget(self.view, stretch=1)

        splitter = q.QSplitter()
        splitter.addWidget(left_pane_splitter)
        splitter.addWidget(right_widget)
        splitter.setSizes([int(splitter.width() * 0.3), int(splitter.width() * 0.7)])
        layout = q.QHBoxLayout(self)
        layout.addWidget(splitter)
        layout.setContentsMargins(0, 0, 0, 0)

    def connectWidgets(self) -> None:
        self.ep_search.connectToFilterModel(self.ep_proxy_model)
        self.ep_search.addFindShortcut(self)
        find_action = q.QAction(self)
        find_action.setShortcut(qg.QKeySequence.Find)
        find_action.triggered.connect(self.graph_search_edit.setFocus)
        self.addAction(find_action)

        self.flow_data.flowDataChanged.connect(lambda reason: self.entry_point_view.clearSelection())
        self.flow_data.flowDataChanged.connect(lambda reason: self.updateFlowNameLabel())
        self.flow_data.fileLoaded.connect(lambda flow: self.updateFlowNameLabel())
        self.flow_name_label.doubleClicked.connect(self.renameFlowFromHeader)
        self.entry_point_view.selectionModel().selectionChanged.connect(self.onEntryPointSelected)
        self.flow_data.entry_point_model.visibilityChanged.connect(self.onEntryPointVisibilityChanged)
        self.entry_point_view.customContextMenuRequested.connect(self.onEntryPointContextMenu)

        connect_model_change_signals(self.container_model, self.flow_data, FlowDataChangeReason.EventParameters)
        self.eventSelected.connect(self.onEventSelectedInWebView)
        self.selectedNodeIdsChanged.connect(self.onSelectedNodeIdsChangedInWebView)
        self.flow_data.flowDataChanged.connect(lambda reason: self.refreshParamModel())

        self.reloadedSignal.connect(self.onWebViewReloaded)
        self.readySignal.connect(self._syncDarkModeToPage)
        self.reloadedSignal.connect(self._syncDarkModeToPage)
        self.readySignal.connect(self._syncMessageTagStylingToPage)
        self.reloadedSignal.connect(self._syncMessageTagStylingToPage)
        self.graph_search_edit.textChanged.connect(self._onGraphSearchTextChanged)
        self.graph_search_edit.returnPressed.connect(lambda: self.view.page().runJavaScript('window.eventEditorStepSearch(1);'))
        self.graph_search_scope_combo.currentIndexChanged.connect(lambda _: self._updateGraphSearch(scroll=True))
        self.graph_search_case_checkbox.toggled.connect(lambda _: self._updateGraphSearch(scroll=False))
        self.graph_search_prev_button.clicked.connect(lambda: self.view.page().runJavaScript('window.eventEditorStepSearch(-1);'))
        self.graph_search_next_button.clicked.connect(lambda: self.view.page().runJavaScript('window.eventEditorStepSearch(1);'))
        self.graph_search_index_edit.editingFinished.connect(self._onGraphSearchIndexChanged)
        self._updateSearchControls(0, -1)

    def onEventParamVisibilityChanged(self, show: bool) -> None:
        self.showEventParams = show

    def onEventMessageVisibilityChanged(self, show: bool) -> None:
        self.showEventMessages = show

    def onEventTagVisibilityChanged(self, show: bool) -> None:
        changed = self.showMessageTags != show
        self.showMessageTags = show
        self.updateMessageLookup(force=changed, report_errors=False)

    def setDarkMode(self, dark_mode: bool) -> None:
        self.dark_mode = dark_mode
        self._syncDarkModeToPage()

    def _syncDarkModeToPage(self) -> None:
        self.view.page().runJavaScript(
            f"(function(){{ if (document.body) document.body.classList.toggle('dark-mode', {'true' if self.dark_mode else 'false'}); }})();"
        )

    def setMessageTagStylingEnabled(self, enabled: bool, refresh: bool = True) -> None:
        self.renderMessageTagsAsStyling = bool(enabled)
        self._syncMessageTagStylingToPage()
        if refresh:
            self.refreshGraphPresentation()

    def setNonTextMessageTagsVisible(self, visible: bool, refresh: bool = True) -> None:
        self.showNonTextMessageTags = bool(visible)
        self._syncMessageTagStylingToPage()
        if refresh:
            self.refreshGraphPresentation()

    def setMessageBlankLinesIncluded(self, included: bool, refresh: bool = True) -> None:
        self.includeMessageBlankLines = bool(included)
        self._syncMessageTagStylingToPage()
        if refresh:
            self.refreshGraphPresentation()

    def setMessageBubbleBreaksShown(self, shown: bool, refresh: bool = True) -> None:
        self.showMessageBubbleBreaks = bool(shown)
        self._syncMessageTagStylingToPage()
        if refresh:
            self.refreshGraphPresentation()

    def _syncMessageTagStylingToPage(self) -> None:
        enabled = 'true' if self.renderMessageTagsAsStyling else 'false'
        show_non_text = 'true' if self.showNonTextMessageTags else 'false'
        include_blank_lines = 'true' if self.includeMessageBlankLines else 'false'
        show_bubble_breaks = 'true' if self.showMessageBubbleBreaks else 'false'
        self.view.page().runJavaScript(
            f"(function(){{ "
            f"if (window.eventEditorSetRenderMessageTagsAsStyling) window.eventEditorSetRenderMessageTagsAsStyling({enabled}); "
            f"if (window.eventEditorSetShowNonTextMessageTags) window.eventEditorSetShowNonTextMessageTags({show_non_text}); "
            f"if (window.eventEditorSetIncludeMessageBlankLines) window.eventEditorSetIncludeMessageBlankLines({include_blank_lines}); "
            f"if (window.eventEditorSetShowMessageBubbleBreaks) window.eventEditorSetShowMessageBubbleBreaks({show_bubble_breaks}); "
            f"}})();"
        )

    def updateFlowNameLabel(self) -> None:
        flow = self.flow_data.flow
        flow_name = ''
        if flow and getattr(flow, 'flowchart', None):
            flow_name = getattr(flow.flowchart, 'name', '') or getattr(flow, 'name', '')
        elif flow:
            flow_name = getattr(flow, 'name', '')
        self.flow_name_label.setText(flow_name)
        self.flow_name_label.setVisible(bool(flow_name))

    def renameFlowFromHeader(self) -> None:
        flow = self.flow_data.flow
        if not flow or not getattr(flow, 'flowchart', None):
            return
        current_name = getattr(flow.flowchart, 'name', '') or getattr(flow, 'name', '')
        text, ok = q.QInputDialog.getText(
            self,
            'Rename',
            'Enter a new name for the flowchart.',
            q.QLineEdit.Normal,
            current_name,
        )
        if not ok or not text:
            return
        flow.name = text
        flow.flowchart.name = text
        self.flow_data.flowDataChanged.emit(FlowDataChangeReason.EventFlowRename)

    def setIsCurrentView(self, is_current: bool) -> None:
        self.is_current = is_current
        if is_current and self.update_timer.isActive():
            self.update_timer.stop()
            self.web_object.flowDataChanged.emit()

    def getGraphData(self) -> list:
        flow = self.flow_data.flow
        if not flow:
            return []
        data = generate_flowchart_graph(flow)
        self._injectMessageTexts(data)
        return self._filterHiddenEntryPointGraphData(data)

    def getMessageArchivePath(self) -> str:
        return self._message_archive_path

    def setMessageArchivePath(self, path: str, force_reload: bool = True, report_errors: bool = True) -> None:
        self._message_archive_path = path or ''
        self._message_archive_missing_text = ''
        self.updateMessageLookup(force=True, report_errors=report_errors)
        if force_reload:
            self.refreshGraphPresentation()

    def clearMessageArchivePath(self, missing_text: str = '') -> None:
        self._message_archive_path = ''
        self._message_archive_missing_text = missing_text or ''
        self._message_lookup_key = ('', frozenset(), self.showMessageTags, self._message_archive_missing_text)
        message_ids = frozenset(self._collectMessageIds())
        self._message_lookup = {
            message_id: self._message_archive_missing_text
            for message_id in message_ids
        } if self._message_archive_missing_text else {}
        self.refreshGraphPresentation()

    def updateMessageLookup(self, force: bool = False, report_errors: bool = False) -> bool:
        message_ids = frozenset(self._collectMessageIds())
        cache_key = (self._message_archive_path, message_ids, self.showMessageTags, self._message_archive_missing_text)
        if not force and cache_key == self._message_lookup_key:
            return False

        self._message_lookup_key = cache_key
        if not self._message_archive_path or not message_ids:
            self._message_lookup = {
                message_id: self._message_archive_missing_text
                for message_id in message_ids
            } if self._message_archive_missing_text and message_ids else {}
            return True

        try:
            self._message_lookup = mals.load_messages_for_ids(
                self._message_archive_path,
                message_ids,
                show_tags=self.showMessageTags,
                include_missing=True,
            )
            return True
        except Exception:
            self._message_lookup = {
                message_id: self._message_archive_missing_text
                for message_id in message_ids
            } if self._message_archive_missing_text and not Path(self._message_archive_path).is_file() else {}
            if report_errors:
                raise
            return True

    def refreshGraphPresentation(self) -> None:
        self.suppress_reload_reselect = True
        self.web_object.fastGraphReloadRequested.emit()
        self.web_object.preserveViewportRequested.emit()
        self.web_object.flowDataChanged.emit()

    def _collectMessageIds(self) -> typing.Set[str]:
        if not self.flow_data.flow or not self.flow_data.flow.flowchart:
            return set()

        message_ids: typing.Set[str] = set()
        for event in self.flow_data.flow.flowchart.events:
            params = getattr(event.data, 'params', None)
            if not params or not getattr(params, 'data', None):
                continue
            value = params.data.get('MessageId')
            if isinstance(value, str) and value:
                message_ids.add(value)
            choice_count = params.data.get('ChoiceNumber')
            if not isinstance(choice_count, int) or choice_count <= 0:
                continue
            for choice_index in range(1, choice_count + 1):
                choice_value = params.data.get(f'ChoiceLabel{choice_index}')
                choice_message_id = self._resolveChoiceLabelMessageId(value, choice_value)
                if choice_message_id:
                    message_ids.add(choice_message_id)
        return message_ids

    def buildMessageLookupReport(self) -> str:
        message_ids = sorted(self._collectMessageIds())
        current_path = self.getMessageArchivePath()
        lines = [f'Current Mals: {current_path or "(none)"}', '']
        if not message_ids:
            lines.append('No MessageId parameters are currently referenced by this flow.')
            return '\n'.join(lines)

        if not current_path:
            lines.append(self._message_archive_missing_text or 'No current Mals archive is selected.')
            lines.append('')
            lines.append('Referenced MSBTs:')
            for prefix in sorted(mals._group_message_ids_by_prefix(message_ids).keys()):
                lines.append(f'- {prefix}')
            return '\n'.join(lines)

        self.updateMessageLookup(report_errors=False)
        missing_by_prefix: typing.Dict[str, typing.Dict[str, typing.List[str]]] = {}
        special_characters: typing.Dict[str, typing.Set[str]] = {}
        for message_id in message_ids:
            if ':' not in message_id:
                missing_by_prefix.setdefault('(invalid MessageId)', {}).setdefault('Malformed MessageId', []).append(message_id)
                continue
            prefix, label = message_id.split(':', 1)
            text = self._message_lookup.get(message_id)
            if text == mals.MSBT_NOT_FOUND_TEXT:
                missing_by_prefix.setdefault(prefix, {}).setdefault('MSBT not found in Mals', []).append(label)
                continue
            if text == mals.MESSAGE_ID_NOT_FOUND_TEXT or text is None:
                missing_by_prefix.setdefault(prefix, {}).setdefault('MessageID not found in provided MSBT', []).append(label)
                continue
            special = {
                f'U+{ord(ch):04X}'
                for ch in text
                if self._isSpecialPreviewCharacter(ch)
            }
            if special:
                special_characters[message_id] = special

        if not missing_by_prefix:
            lines.append('No missing MSBTs or MessageIDs were found for the current graph.')
        else:
            lines.append('Missing MSBTs and MessageIDs grouped by MSBT:')
            for prefix in sorted(missing_by_prefix.keys()):
                lines.append('')
                lines.append(prefix)
                for reason in sorted(missing_by_prefix[prefix].keys()):
                    lines.append(f'  {reason}:')
                    for label in sorted(missing_by_prefix[prefix][reason]):
                        lines.append(f'    - {label}')

        if special_characters:
            lines.append('')
            lines.append('Special characters outside the usual text preview range were found:')
            for message_id in sorted(special_characters.keys()):
                chars = ', '.join(sorted(special_characters[message_id]))
                lines.append(f'- {message_id}: {chars}')
            lines.append('')
            lines.append('Possible rendering strategies: map known codes to named icons, show fallback labels, or add custom font/sprite support.')
        return '\n'.join(lines)

    def _isSpecialPreviewCharacter(self, char: str) -> bool:
        codepoint = ord(char)
        if codepoint in (0x09, 0x0A, 0x0D):
            return False
        if codepoint < 0x20:
            return True
        if 0xE000 <= codepoint <= 0xF8FF:
            return True
        if 0xF0000 <= codepoint <= 0xFFFFD:
            return True
        if 0x100000 <= codepoint <= 0x10FFFD:
            return True
        return codepoint == 0xFFFD

    def _resolveChoiceLabelMessageId(self, base_message_id: typing.Any, choice_value: typing.Any) -> typing.Optional[str]:
        if isinstance(choice_value, str):
            normalized = choice_value.strip()
            if not normalized:
                return None
            if normalized.startswith('EventFlowMsg/'):
                return normalized
            if isinstance(base_message_id, str) and base_message_id:
                prefix = base_message_id.rsplit(':', 1)[0] if ':' in base_message_id else base_message_id
                if normalized.isdigit():
                    return f'{prefix}:{int(normalized):04d}'
                return f'{prefix}:{normalized}'
            return None

        if not isinstance(choice_value, int) or choice_value < 0:
            return None
        if not isinstance(base_message_id, str) or not base_message_id:
            return None
        prefix = base_message_id.rsplit(':', 1)[0] if ':' in base_message_id else base_message_id
        return f'{prefix}:{choice_value:04d}'

    def _injectMessageTexts(self, data: list) -> None:
        if not self._message_lookup:
            return

        for entry in data:
            if entry.get('type') != 'node':
                continue
            node_data = entry.get('data') or {}
            params = node_data.get('params')
            if not isinstance(params, dict):
                continue
            message_id = params.get('MessageId')
            if not isinstance(message_id, str):
                message_id = None
            if message_id:
                message_text = self._message_lookup.get(message_id)
                if message_text:
                    node_data['_message_text'] = message_text

            choice_count = params.get('ChoiceNumber')
            if not isinstance(choice_count, int) or choice_count <= 0:
                continue
            choice_texts: typing.Dict[str, str] = {}
            choice_items: typing.List[typing.Dict[str, typing.Any]] = []
            for choice_index in range(1, choice_count + 1):
                key = f'ChoiceLabel{choice_index}'
                choice_value = params.get(key)
                choice_message_id = self._resolveChoiceLabelMessageId(message_id, choice_value)
                if not choice_message_id:
                    continue
                choice_text = self._message_lookup.get(choice_message_id)
                if choice_text is not None:
                    choice_texts[key] = choice_text
                    choice_items.append({
                        'index': choice_index,
                        'message_id': choice_message_id,
                        'text': choice_text,
                    })
            if choice_texts:
                node_data['_choice_label_texts'] = choice_texts
            if choice_items:
                node_data['_choice_texts'] = choice_items

    def _onGraphSearchTextChanged(self, _text: str) -> None:
        self._updateGraphSearch(scroll=True)

    def _updateGraphSearch(self, scroll: bool) -> None:
        text = json.dumps(self.graph_search_edit.text())
        scope = json.dumps(self.graph_search_scope_combo.currentData() or 'all')
        case_insensitive = 'true' if self.graph_search_case_checkbox.isChecked() else 'false'
        should_scroll = 'true' if scroll else 'false'
        self.view.page().runJavaScript(
            f'window.eventEditorSetSearchQuery({text}, {case_insensitive}, {should_scroll}, {scope});'
        )

    def _updateSearchControls(self, count: int, index: int) -> None:
        blocker = qc.QSignalBlocker(self.graph_search_index_edit)
        if count <= 0:
            self.graph_search_index_edit.setEnabled(False)
            self.graph_search_index_edit.setText('0')
            self.graph_search_total_label.setText('/0')
            self._resizeGraphSearchIndexEdit()
            self.graph_search_prev_button.setEnabled(False)
            self.graph_search_next_button.setEnabled(False)
            del blocker
            return
        self.graph_search_index_edit.setEnabled(True)
        self.graph_search_index_edit.setText(str(max(1, index + 1)))
        self.graph_search_total_label.setText(f'/{count}')
        self._resizeGraphSearchIndexEdit()
        self.graph_search_prev_button.setEnabled(count > 1)
        self.graph_search_next_button.setEnabled(count > 1)
        del blocker

    def onGraphSearchResultsChanged(self, count: int, index: int) -> None:
        self._updateSearchControls(count, index)

    def _onGraphSearchIndexChanged(self) -> None:
        try:
            value = int(self.graph_search_index_edit.text())
        except ValueError:
            return
        if value <= 0:
            return
        self.view.page().runJavaScript(f'window.eventEditorSetSearchIndex({value - 1});')

    def _resizeGraphSearchIndexEdit(self) -> None:
        text = self.graph_search_index_edit.text() or '0'
        width = self.graph_search_index_edit.fontMetrics().horizontalAdvance(text) + 4
        self.graph_search_index_edit.setFixedWidth(max(10, width))

    def _getNextEvents(self, event: Event) -> typing.Iterable[Event]:
        data = event.data
        if isinstance(data, (ActionEvent, JoinEvent, SubFlowEvent)):
            if data.nxt.v:
                yield data.nxt.v
        elif isinstance(data, SwitchEvent):
            for case in data.cases.values():
                if case.v:
                    yield case.v
        elif isinstance(data, ForkEvent):
            for fork in data.forks:
                if fork.v:
                    yield fork.v
            if data.join.v:
                yield data.join.v

    def _collectReachableEvents(self, entry_point: EntryPoint) -> typing.Set[Event]:
        reachable: typing.Set[Event] = set()
        if not entry_point.main_event.v:
            return reachable

        queue: typing.List[Event] = [entry_point.main_event.v]
        while queue:
            event = queue.pop()
            if event in reachable:
                continue
            reachable.add(event)
            queue.extend(self._getNextEvents(event))
        return reachable

    def _invalidateEntryPointReachabilityCache(self) -> None:
        self._entry_point_reachable_cache_key = None
        self._entry_point_reachable_cache = []

    def _entryPointReachableSets(self) -> typing.List[typing.Set[Event]]:
        if not self.flow_data.flow or not self.flow_data.flow.flowchart:
            self._invalidateEntryPointReachabilityCache()
            return []

        flowchart = self.flow_data.flow.flowchart
        cache_key = (id(flowchart), len(flowchart.entry_points), len(flowchart.events))
        if self._entry_point_reachable_cache_key == cache_key and len(self._entry_point_reachable_cache) == len(flowchart.entry_points):
            return self._entry_point_reachable_cache

        reachable_sets = [self._collectReachableEvents(entry_point) for entry_point in flowchart.entry_points]
        self._entry_point_reachable_cache_key = cache_key
        self._entry_point_reachable_cache = reachable_sets
        return reachable_sets

    def _allEntryPointRows(self) -> typing.List[int]:
        if not self.flow_data.flow or not self.flow_data.flow.flowchart:
            return []
        return list(range(len(self.flow_data.flow.flowchart.entry_points)))

    def _connectedEntryPointRowsForNode(self, node_id: int) -> typing.List[int]:
        if not self.flow_data.flow or not self.flow_data.flow.flowchart:
            return []

        flowchart = self.flow_data.flow.flowchart
        if node_id < 0:
            row = -1000 - int(node_id)
            return [row] if 0 <= row < len(flowchart.entry_points) else []

        if not (0 <= node_id < len(flowchart.events)):
            return []

        target_event = flowchart.events[node_id]
        rows: typing.List[int] = []
        for row, reachable in enumerate(self._entryPointReachableSets()):
            if target_event in reachable:
                rows.append(row)
        return rows

    def _filterHiddenEntryPointGraphData(self, data: list) -> list:
        if not self.flow_data.flow or not self.flow_data.flow.flowchart:
            return data

        hidden_names = self.flow_data.entry_point_model.hiddenEntryPointNames()
        if not hidden_names:
            return data

        flowchart = self.flow_data.flow.flowchart
        visible_reachable: typing.Set[Event] = set()
        hidden_reachable: typing.Set[Event] = set()

        reachable_sets = self._entryPointReachableSets()
        for entry_point, reachable in zip(flowchart.entry_points, reachable_sets):
            if entry_point.name in hidden_names:
                hidden_reachable.update(reachable)
            else:
                visible_reachable.update(reachable)

        hidden_only_events = hidden_reachable - visible_reachable
        event_idx_by_event = {event: idx for idx, event in enumerate(flowchart.events)}
        hidden_node_ids = {
            event_idx_by_event[event] for event in hidden_only_events
            if event in event_idx_by_event
        }
        hidden_node_ids.update(
            -1000 - idx for idx, entry_point in enumerate(flowchart.entry_points)
            if entry_point.name in hidden_names
        )

        if not hidden_node_ids:
            return data

        filtered = []
        for entry in data:
            if entry['type'] == 'node':
                if entry['id'] in hidden_node_ids:
                    continue
            elif entry['type'] == 'edge':
                if entry['source'] in hidden_node_ids or entry['target'] in hidden_node_ids:
                    continue
            filtered.append(entry)
        return filtered

    def export(self) -> None:
        if not self.flow_data.flow:
            return
        path = q.QFileDialog.getSaveFileName(self, 'Select a location for the graph data', self.flow_data.flow.name + '.json', 'Data (*.json)')[0]
        if not path:
            return
        data = self.web_object.getData()
        try:
            with open(path, 'w') as f:
                json.dump(data, f, default=lambda x: str(x))
        except:
            q.QMessageBox.critical(self, 'Export graph data', 'Failed to write to ' + path)
    
    def export_definitions(self) -> None:
        try:
            aj.export_definitions(self.flow_data.flow, self)
        except:
            q.QMessageBox.critical(self, 'Export actor definition data', 'Failed to write to ' + str(aj._actor_definitions_path))
    
    def reorder_event_parameters(self) -> None:
        ft.reorder_event_flow_parameters(self.flow_data.flow)
        self.flow_data.flowDataChanged.emit(FlowDataChangeReason.EventParameters)

    def reload(self) -> None:
        self.view.reload()

    def currentSelectedNodeId(self) -> typing.Optional[int]:
        if self.selected_node_id is not None and self.flow_data.flow and self.flow_data.flow.flowchart:
            if self.selected_node_id >= 0:
                if self.selected_node_id < len(self.flow_data.flow.flowchart.events):
                    return self.selected_node_id
            else:
                row = -1000 - self.selected_node_id
                if 0 <= row < len(self.flow_data.flow.flowchart.entry_points):
                    return self.selected_node_id

        if self.flow_data.flow and self.flow_data.flow.flowchart and self.selected_event:
            try:
                return self.flow_data.flow.flowchart.events.index(self.selected_event)
            except ValueError:
                pass

        selected_rows = self._getSelectedEntryPointRowsFromView()
        if selected_rows:
            return -1000 - selected_rows[-1]
        return None

    def reloadPagePreservingSelection(self) -> None:
        selected_node_id = self.currentSelectedNodeId()
        if selected_node_id is not None:
            self.pending_reveal_node_id = int(selected_node_id)
            self.pending_reveal_duration_ms = 500
        self.suppress_reload_reselect = True
        self.view.reload()

    def refreshDisplayOptionsPreservingSelection(self) -> None:
        self.pending_reveal_node_id = None
        self.pending_reveal_duration_ms = None
        self.suppress_reload_reselect = True
        self.web_object.preserveViewportRequested.emit()
        self.web_object.fastGraphReloadRequested.emit()
        self.web_object.flowDataChanged.emit()

    def onWebViewReloaded(self) -> None:
        if self.pending_reveal_event and self.flow_data.flow and self.flow_data.flow.flowchart:
            try:
                new_idx = self.flow_data.flow.flowchart.events.index(self.pending_reveal_event)
                self.web_object.revealRequested.emit(new_idx)
            except ValueError:
                pass
            finally:
                self.pending_reveal_event = None

        if self.pending_reveal_node_id is not None:
            duration_ms = self.pending_reveal_duration_ms
            if duration_ms == 0:
                self.web_object.instantRevealRequested.emit(self.pending_reveal_node_id)
            else:
                self.web_object.revealRequested.emit(self.pending_reveal_node_id)
            self.pending_reveal_node_id = None
            self.pending_reveal_duration_ms = None

        self._updateGraphSearch(scroll=False)

        if self.suppress_reload_reselect:
            self.suppress_reload_reselect = False
            return
        if self.selected_event and self.flow_data.flow and self.flow_data.flow.flowchart:
            try:
                self.flow_data.flow.flowchart.events.index(self.selected_event)
            except ValueError:
                self.container_model.set(None)
                self.container_stacked_widget.setCurrentIndex(0)

    def _keepDialogOpen(self, dialog: q.QDialog) -> None:
        self._open_dialogs.append(dialog)
        def cleanup(*args) -> None:
            try:
                self._open_dialogs.remove(dialog)
            except ValueError:
                pass
        dialog.finished.connect(cleanup)

    def refreshParamModel(self) -> bool:
        if self.selected_event and hasattr(self.selected_event.data, 'params'):
            if not self.selected_event.data.params: # type: ignore
                self.selected_event.data.params = Container() # type: ignore
            self.container_model.set(self.selected_event.data.params) # type: ignore
            self.container_stacked_widget.setCurrentIndex(1)
            return True
        return False

    def onEventSelectedInWebView(self, idx: int) -> None:
        selection_model = self.entry_point_view.selectionModel()
        self.selected_node_id = idx
        if idx >= 0:
            if selection_model:
                blocker = qc.QSignalBlocker(selection_model)
                selection_model.clearSelection()
                self.entry_point_view.setCurrentIndex(qc.QModelIndex())
                del blocker
            event = self.flow_data.flow.flowchart.events[idx]
            self.selected_event = event
            if self.refreshParamModel():
                return
        else:
            self.selected_event = None
            if self.flow_data.flow and self.flow_data.flow.flowchart:
                row = -1000 - idx
                if 0 <= row < len(self.flow_data.flow.flowchart.entry_points):
                    source_index = self.flow_data.entry_point_model.createIndex(row, 0)
                    proxy_index = self.ep_proxy_model.mapFromSource(source_index)
                    if selection_model:
                        blocker = qc.QSignalBlocker(selection_model)
                        selection_model.clearSelection()
                        self.entry_point_view.setCurrentIndex(qc.QModelIndex())
                        if proxy_index.isValid():
                            selection_model.setCurrentIndex(
                                proxy_index,
                                qc.QItemSelectionModel.ClearAndSelect | qc.QItemSelectionModel.Current | qc.QItemSelectionModel.Rows
                            )
                            selection_model.select(
                                proxy_index,
                                qc.QItemSelectionModel.ClearAndSelect | qc.QItemSelectionModel.Current | qc.QItemSelectionModel.Rows
                            )
                            self.entry_point_view.scrollTo(proxy_index, q.QAbstractItemView.PositionAtCenter)
                            self.entry_point_view.viewport().update()
                        del blocker

        self.container_model.set(None)
        self.container_stacked_widget.setCurrentIndex(0)

    def onSelectedNodeIdsChangedInWebView(self, node_ids: typing.List[int]) -> None:
        if not self.flow_data.flow or not self.flow_data.flow.flowchart:
            return

        selection_model = self.entry_point_view.selectionModel()
        if not selection_model:
            return

        rows = sorted({
            -1000 - int(node_id)
            for node_id in node_ids
            if int(node_id) < 0
        })

        blocker = qc.QSignalBlocker(selection_model)
        selection_model.clearSelection()
        self.entry_point_view.setCurrentIndex(qc.QModelIndex())

        valid_proxy_indexes: typing.List[qc.QModelIndex] = []
        for row in rows:
            if 0 <= row < len(self.flow_data.flow.flowchart.entry_points):
                source_index = self.flow_data.entry_point_model.createIndex(row, 0)
                proxy_index = self.ep_proxy_model.mapFromSource(source_index)
                if proxy_index.isValid():
                    valid_proxy_indexes.append(proxy_index)

        if valid_proxy_indexes:
            for proxy_index in valid_proxy_indexes:
                selection_model.select(
                    proxy_index,
                    qc.QItemSelectionModel.Select | qc.QItemSelectionModel.Rows
                )
            selection_model.setCurrentIndex(
                valid_proxy_indexes[-1],
                qc.QItemSelectionModel.NoUpdate
            )
            self.entry_point_view.viewport().update()

        del blocker

    def onFlowDataChanged(self, reason: FlowDataChangeReason) -> None:
        if reason & (FlowDataChangeReason.Reset | FlowDataChangeReason.Events | FlowDataChangeReason.EventFlowRename):
            self._invalidateEntryPointReachabilityCache()
        message_lookup_changed = False
        if (self._message_archive_path or self._message_archive_missing_text) and reason & (
            FlowDataChangeReason.Reset |
            FlowDataChangeReason.Events |
            FlowDataChangeReason.EventParameters
        ):
            message_lookup_changed = self.updateMessageLookup(
                force=bool(reason & FlowDataChangeReason.Reset),
                report_errors=False,
            )

        should_reload = bool(reason & (FlowDataChangeReason.Reset | FlowDataChangeReason.Actors | FlowDataChangeReason.Events))
        if self.showEventParams or self.showEventMessages:
            should_reload = should_reload or bool(reason & FlowDataChangeReason.EventParameters)
        should_reload = should_reload or message_lookup_changed
        if not should_reload:
            return
        if self.is_current:
            if self.pending_reveal_event is None and self.pending_reveal_node_id is None:
                if not bool(reason & FlowDataChangeReason.Reset):
                    self.web_object.preserveViewportRequested.emit()
                self.web_object.fastGraphReloadRequested.emit()
            self.web_object.flowDataChanged.emit()
        else:
            self.update_timer.start(15*1000)

    def onEntryPointSelected(self, selected, deselected) -> None:
        selection_model = self.entry_point_view.selectionModel()
        if not selection_model:
            return

        selected_rows = selection_model.selectedRows()
        if len(selected_rows) != 1:
            return

        idx = selected_rows[0]
        if not idx.isValid():
            return
        source_row = self.ep_proxy_model.mapToSource(idx).row()
        target_node_id = -1000 - source_row
        if self.flow_data.entry_point_model.isHiddenRow(source_row):
            self.pending_reveal_node_id = target_node_id
            self.pending_reveal_duration_ms = 500
            self.flow_data.entry_point_model.setRowsHidden([source_row], False)
            return
        self.selectRequested.emit(target_node_id)

    def onEntryPointVisibilityChanged(self) -> None:
        self.web_object.entryPointFilterStateChanged.emit(bool(self.flow_data.entry_point_model.hiddenEntryPointNames()))
        self.suppress_reload_reselect = True
        self.web_object.fastGraphReloadRequested.emit()
        self.web_object.preserveViewportRequested.emit()
        self.web_object.flowDataChanged.emit()

    def webGoToSubflowEntryPoint(self, node_id: int) -> None:
        if not self.flow_data.flow or not self.flow_data.flow.flowchart:
            return
        flow = self.flow_data.flow
        flowchart = flow.flowchart
        if not (0 <= node_id < len(flowchart.events)):
            return

        event = flowchart.events[node_id]
        event_data = getattr(event, 'data', None)
        if not isinstance(event_data, SubFlowEvent):
            return

        entry_point_name = event_data.entry_point_name
        if not entry_point_name:
            return

        local_flow_names = {
            name for name in (
                getattr(flow, 'name', ''),
                getattr(flowchart, 'name', ''),
            ) if name
        }
        target_flow_name = event_data.res_flowchart_name or getattr(flowchart, 'name', '') or getattr(flow, 'name', '')
        if event_data.res_flowchart_name and target_flow_name not in local_flow_names:
            self.externalSubflowOpenRequested.emit(target_flow_name, entry_point_name)
            return

        self.selectEntryPointByName(entry_point_name)

    def selectEntryPointByName(self, entry_point_name: str) -> None:
        if not self.flow_data.flow or not self.flow_data.flow.flowchart:
            return
        flowchart = self.flow_data.flow.flowchart
        for row, entry_point in enumerate(flowchart.entry_points):
            if entry_point.name != entry_point_name:
                continue

            source_index = self.flow_data.entry_point_model.index(row, 0)
            mapped_index = self.ep_proxy_model.mapFromSource(source_index)
            if mapped_index.isValid():
                self.entry_point_view.setCurrentIndex(mapped_index)
                self.entry_point_view.scrollTo(mapped_index)

            target_node_id = -1000 - row
            self.pending_reveal_node_id = target_node_id
            if self.flow_data.entry_point_model.setRowsHidden([row], False):
                return
            self.selectRequested.emit(target_node_id)
            return

        q.QMessageBox.information(
            self,
            'Go to entry point',
            f'This file does not contain an entry point named "{entry_point_name}".',
        )

    def webShowOnlyConnectedEvents(self, node_id: int) -> None:
        rows_to_show = set(self._connectedEntryPointRowsForNode(node_id))
        all_rows = self._allEntryPointRows()
        if not all_rows or not rows_to_show:
            return

        self.pending_reveal_node_id = int(node_id)
        self.suppress_reload_reselect = True
        model = self.flow_data.entry_point_model
        changed = False
        changed = model.setRowsHidden(rows_to_show, False) or changed
        rows_to_hide = [row for row in all_rows if row not in rows_to_show]
        changed = model.setRowsHidden(rows_to_hide, True) or changed
        if not changed:
            self.onEntryPointVisibilityChanged()

    def webShowAllEvents(self, reveal_node_id: typing.Optional[int] = None) -> None:
        all_rows = self._allEntryPointRows()
        if not all_rows:
            return
        if reveal_node_id is not None:
            self.pending_reveal_node_id = int(reveal_node_id)
            self.suppress_reload_reselect = True
        if not self.flow_data.entry_point_model.setRowsHidden(all_rows, False):
            self.onEntryPointVisibilityChanged()

    def delayedSelect(self, event: Event) -> None:
        self.pending_reveal_event = event
        self.suppress_reload_reselect = True

    def _getSelectedEntryPointRowsFromView(self) -> typing.List[int]:
        selection_model = self.entry_point_view.selectionModel()
        if not selection_model:
            return []
        return sorted({
            self.ep_proxy_model.mapToSource(index).row()
            for index in selection_model.selectedRows()
            if index.isValid()
        })

    def _entryPointRowsToNodeIds(self, rows: typing.Iterable[int]) -> typing.List[int]:
        return [-1000 - row for row in rows]

    def _serializeEntryPointRowsPayload(self, entry_rows: typing.Iterable[int]) -> typing.Dict[str, typing.Any]:
        assert self.flow_data.flow and self.flow_data.flow.flowchart
        flowchart = self.flow_data.flow.flowchart
        selected_rows = sorted(set(row for row in entry_rows if 0 <= row < len(flowchart.entry_points)))
        index_by_event = {event: idx for idx, event in enumerate(flowchart.events)}
        event_indices: typing.Set[int] = set()
        for row in selected_rows:
            entry_point = flowchart.entry_points[row]
            for event in self._collectReachableEvents(entry_point):
                idx = index_by_event.get(event)
                if idx is not None:
                    event_indices.add(idx)

        payload = self._serializeSelectedEvents(sorted(event_indices))
        payload['entry_points'] = self._serializeSelectedEntryPoints(
            selected_rows,
            {record['source_idx'] for record in payload.get('events', [])},
        )
        return payload

    def copySelectedEntryPoints(self) -> None:
        rows = self._getSelectedEntryPointRowsFromView()
        if not rows:
            return
        try:
            payload = self._serializeEntryPointRowsPayload(rows)
        except Exception as exc:
            traceback.print_exc()
            q.QMessageBox.critical(self, 'Copy entry points', f'Failed to copy entry point trees.\n\n{exc}')
            return
        if not payload.get('entry_points'):
            q.QMessageBox.information(self, 'Copy entry points', 'No entry point trees were copied.')
            return
        self._writeClipboardPayload(payload)

    def _readEntryPointPayloadFromClipboard(self) -> typing.Optional[typing.Dict[str, typing.Any]]:
        payload = self._readClipboardPayload()
        if not payload:
            return None
        if not payload.get('entry_points'):
            return None
        return payload

    def pasteEntryPoints(self) -> None:
        payload = self._readEntryPointPayloadFromClipboard()
        if not payload:
            q.QMessageBox.information(self, 'Paste entry points', 'No compatible entry point tree data was found on the clipboard.')
            return
        self._pastePayload(payload, reveal_new_events=True, action_name='Paste entry points')

    def exportSelectedEntryPointsXml(self) -> None:
        rows = self._getSelectedEntryPointRowsFromView()
        if not rows:
            return
        try:
            payload = self._serializeEntryPointRowsPayload(rows)
        except Exception as exc:
            traceback.print_exc()
            q.QMessageBox.critical(self, 'Export entry points', f'Failed to export entry point trees.\n\n{exc}')
            return
        if not payload.get('entry_points'):
            return
        default_name = 'entry_points.xml'
        if len(rows) == 1 and self.flow_data.flow and self.flow_data.flow.flowchart:
            default_name = f'{self.flow_data.flow.flowchart.entry_points[rows[0]].name}.entry_point.xml'
        path = q.QFileDialog.getSaveFileName(self, 'Export entry point trees...', default_name, 'XML (*.xml)')[0]
        if not path:
            return
        try:
            with open(path, 'wt', encoding='utf-8') as file:
                file.write(eptxml.dumps_payload(payload))
        except Exception as exc:
            q.QMessageBox.critical(self, 'Export entry points', f'Failed to export entry point trees.\n\n{exc}')

    def importEntryPointsXml(self) -> None:
        path = q.QFileDialog.getOpenFileName(self, 'Import entry point trees...', 'entry_points.xml', 'XML (*.xml)')[0]
        if not path:
            return
        try:
            with open(path, 'rt', encoding='utf-8') as file:
                payload = eptxml.loads_payload(file.read())
        except Exception as exc:
            q.QMessageBox.critical(self, 'Import entry points', f'Failed to import entry point trees.\n\n{exc}')
            return
        if not payload.get('entry_points'):
            q.QMessageBox.information(self, 'Import entry points', 'The selected XML does not contain any entry point trees.')
            return
        self._pastePayload(payload, reveal_new_events=True, action_name='Import entry points')

    def toggleSelectedEntryPointsVisibility(self) -> None:
        rows = self._getSelectedEntryPointRowsFromView()
        if not rows:
            return
        self.flow_data.entry_point_model.toggleRowsVisibility(rows)

    def _selectedEntryPointVisibilityAction(self) -> typing.Tuple[str, typing.Optional[bool]]:
        rows = self._getSelectedEntryPointRowsFromView()
        if not rows:
            return 'Hide selected', None
        hidden_count = sum(1 for row in rows if self.flow_data.entry_point_model.isHiddenRow(row))
        shown_count = len(rows) - hidden_count
        if hidden_count > shown_count:
            return 'Show selected', False
        return 'Hide selected', True

    def setSelectedEntryPointsHidden(self, hidden: bool) -> None:
        rows = self._getSelectedEntryPointRowsFromView()
        if not rows:
            return
        self.flow_data.entry_point_model.setRowsHidden(rows, hidden)

    def showOnlySelectedEntryPoints(self) -> None:
        selected_rows = self._getSelectedEntryPointRowsFromView()
        all_rows = self._allEntryPointRows()
        if not selected_rows or not all_rows:
            return

        selected_set = set(selected_rows)
        rows_to_hide = [row for row in all_rows if row not in selected_set]
        model = self.flow_data.entry_point_model
        changed = False
        changed = model.setRowsHidden(selected_rows, False) or changed
        changed = model.setRowsHidden(rows_to_hide, True) or changed
        if not changed:
            self.onEntryPointVisibilityChanged()

    def deleteSelectedEntryPoints(self) -> None:
        if not self.flow_data.flow or not self.flow_data.flow.flowchart:
            return

        flowchart = self.flow_data.flow.flowchart
        selected_rows = self._getSelectedEntryPointRowsFromView()
        if not selected_rows:
            return

        selected_rows_set = set(selected_rows)
        selected_reachable: typing.Set[Event] = set()
        unselected_reachable: typing.Set[Event] = set()

        for row, entry_point in enumerate(flowchart.entry_points):
            reachable = self._collectReachableEvents(entry_point)
            if row in selected_rows_set:
                selected_reachable.update(reachable)
            else:
                unselected_reachable.update(reachable)

        exclusive_events = selected_reachable - unselected_reachable
        event_idx_by_event = {event: idx for idx, event in enumerate(flowchart.events)}
        node_ids = self._entryPointRowsToNodeIds(selected_rows)
        node_ids.extend(
            event_idx_by_event[event]
            for event in exclusive_events
            if event in event_idx_by_event
        )
        self.webRemoveEvents(node_ids)

    def onEntryPointContextMenu(self, pos) -> None:
        selection_model = self.entry_point_view.selectionModel()
        index = self.entry_point_view.indexAt(pos)
        if index.isValid() and selection_model and not selection_model.isSelected(index):
            selection_model.clearSelection()
            selection_model.select(index, qc.QItemSelectionModel.Select | qc.QItemSelectionModel.Rows)
            self.entry_point_view.setCurrentIndex(index)

        selected_rows = self._getSelectedEntryPointRowsFromView()
        selected_count = len(selected_rows)

        menu = q.QMenu(self)
        if selected_count:
            if selected_count == 1:
                menu.addAction('Add new child...', lambda: self.webAddEntryPointChild(self._entryPointRowsToNodeIds(selected_rows)[0]))
                menu.addSeparator()
            toggle_label, hidden_target = self._selectedEntryPointVisibilityAction()
            if hidden_target is None:
                menu.addAction(toggle_label, self.toggleSelectedEntryPointsVisibility)
            else:
                menu.addAction(toggle_label, lambda checked=False, hidden=hidden_target: self.setSelectedEntryPointsHidden(hidden))
            menu.addAction('Show only selected', self.showOnlySelectedEntryPoints)
            menu.addAction('Show All', lambda checked=False: self.webShowAllEvents())
            menu.addSeparator()
            menu.addAction('&Copy', self.copySelectedEntryPoints)
        menu.addAction('&Paste', self.pasteEntryPoints)
        menu.addAction('E&xport', self.exportSelectedEntryPointsXml)
        menu.addAction('&Import', self.importEntryPointsXml)
        if selected_count:
            menu.addSeparator()
            if selected_count == 1:
                menu.addAction('&Delete', self.deleteSelectedEntryPoints)
            else:
                menu.addAction(f'&Delete selected ({selected_count})', self.deleteSelectedEntryPoints)
        menu.exec_(self.entry_point_view.viewport().mapToGlobal(pos))

    def webEditEvent(self, idx: int) -> None:
        if idx < 0:
            return
        show_event_editor(self, self.flow_data, idx)

    def webAddEntryPoint(self, event_idx: int) -> None:
        if event_idx < 0:
            return

        ep_name, ok = q.QInputDialog.getText(self, 'Add entry point', f'Name of the new entry point:', q.QLineEdit.Normal)
        if not ok or not ep_name:
            return

        ep = EntryPoint(ep_name)
        assert self.flow_data.flow and self.flow_data.flow.flowchart
        ep.main_event.v = self.flow_data.flow.flowchart.events[event_idx]
        self.flow_data.entry_point_model.append(ep)

    def webRemoveEntryPoint(self, ep_idx: int) -> None:
        try:
            self.flow_data.entry_point_model.removeRow(ep_idx)
        except IndexError as e:
            q.QMessageBox.critical(self, 'Bug', f'An error has occurred: {e}\n\nPlease report this issue and mention what you were doing when this message showed up.')

    def webRenameEntryPoint(self, node_id: int) -> None:
        if node_id >= 0 or not self.flow_data.flow or not self.flow_data.flow.flowchart:
            return

        entry_point_row = -1000 - int(node_id)
        flowchart = self.flow_data.flow.flowchart
        if not (0 <= entry_point_row < len(flowchart.entry_points)):
            return

        entry_point = flowchart.entry_points[entry_point_row]
        new_name, ok = q.QInputDialog.getText(
            self,
            'Rename entry point',
            'Enter a new entry point name.',
            q.QLineEdit.Normal,
            entry_point.name,
        )
        if not ok or not new_name:
            return

        model_index = self.flow_data.entry_point_model.createIndex(entry_point_row, 0)
        self.flow_data.entry_point_model.setData(model_index, new_name, qc.Qt.EditRole)

    def webAddEntryPointChild(self, node_id: int) -> None:
        if node_id >= 0 or not self.flow_data.flow or not self.flow_data.flow.flowchart:
            return

        entry_point_row = -1000 - int(node_id)
        flowchart = self.flow_data.flow.flowchart
        if not (0 <= entry_point_row < len(flowchart.entry_points)):
            return

        entry_point = flowchart.entry_points[entry_point_row]
        new_event = self.createNewEvent()
        if not new_event:
            return

        if entry_point.main_event.v:
            self._doAddEventAbove([], entry_point.main_event.v, new_event)
        entry_point.main_event.v = new_event

        self.flow_data.flowDataChanged.emit(FlowDataChangeReason.Events)
        self.delayedSelect(new_event)

    def _expandCopySelection(self, selected_indices: typing.Iterable[int]) -> typing.List[int]:
        if not self.flow_data.flow or not self.flow_data.flow.flowchart:
            return []

        events = self.flow_data.flow.flowchart.events
        index_by_event = {event: idx for idx, event in enumerate(events)}
        expanded = {idx for idx in selected_indices if 0 <= idx < len(events)}

        for idx in list(expanded):
            event = events[idx]
            if isinstance(event.data, ForkEvent):
                self._collectForkStructureIndices(event, index_by_event, expanded)

        return sorted(expanded)

    def _collectForkStructureIndices(self, fork_event: Event, index_by_event: typing.Dict[Event, int],
                                     expanded: typing.Set[int]) -> None:
        assert isinstance(fork_event.data, ForkEvent)
        join_event = fork_event.data.join.v
        join_idx = index_by_event.get(join_event)
        if join_idx is not None:
            expanded.add(join_idx)

        for fork in fork_event.data.forks:
            self._collectBranchIndicesUntilStop(fork.v, join_event, index_by_event, expanded, set())

    def _collectBranchIndicesUntilStop(self, event: typing.Optional[Event], stop_event: typing.Optional[Event],
                                       index_by_event: typing.Dict[Event, int], expanded: typing.Set[int],
                                       visited: typing.Set[typing.Tuple[int, typing.Optional[int]]]) -> None:
        if not event:
            return

        visit_key = (id(event), id(stop_event) if stop_event else None)
        if visit_key in visited:
            return
        visited.add(visit_key)

        idx = index_by_event.get(event)
        if idx is not None:
            expanded.add(idx)

        if event == stop_event:
            return

        data = event.data
        if isinstance(data, (ActionEvent, JoinEvent, SubFlowEvent)):
            self._collectBranchIndicesUntilStop(data.nxt.v, stop_event, index_by_event, expanded, visited)
        elif isinstance(data, SwitchEvent):
            for case in data.cases.values():
                self._collectBranchIndicesUntilStop(case.v, stop_event, index_by_event, expanded, visited)
        elif isinstance(data, ForkEvent):
            self._collectForkStructureIndices(event, index_by_event, expanded)
            self._collectBranchIndicesUntilStop(data.join.v, stop_event, index_by_event, expanded, visited)

    def _cloneContainerData(self, container: typing.Optional[Container]) -> typing.Optional[typing.Dict[str, typing.Any]]:
        if not container:
            return None
        return copy.deepcopy(container.data)

    def _makeContainerFromData(self, data: typing.Optional[typing.Dict[str, typing.Any]]) -> typing.Optional[Container]:
        if data is None:
            return None
        container = Container()
        container.data = copy.deepcopy(data)
        return container

    def _copyEntryPointItems(self, entry_point: EntryPoint) -> typing.Dict[str, typing.Any]:
        return copy.deepcopy(getattr(entry_point, 'items', {}) or {})

    def _setEntryPointItems(self, entry_point: EntryPoint, items: typing.Dict[str, typing.Any]) -> None:
        if not hasattr(entry_point, 'items'):
            return
        try:
            entry_point.items = copy.deepcopy(items or {})
        except AttributeError:
            pass

    def _serializeActor(self, actor: Actor) -> typing.Dict[str, typing.Any]:
        return {
            'identifier': (actor.identifier.name, actor.identifier.sub_name),
            'argument_name': actor.argument_name,
            'actions': [action.v for action in actor.actions],
            'queries': [query.v for query in actor.queries],
            'params': self._cloneContainerData(actor.params),
            'concurrent_clips': actor.concurrent_clips,
        }

    def _selectedEntryPointRows(self, node_ids: typing.Iterable[int]) -> typing.List[int]:
        if not self.flow_data.flow or not self.flow_data.flow.flowchart:
            return []
        num_entry_points = len(self.flow_data.flow.flowchart.entry_points)
        rows = []
        for node_id in sorted(set(int(idx) for idx in node_ids if int(idx) < 0)):
            row = -1000 - node_id
            if 0 <= row < num_entry_points:
                rows.append(row)
        return rows

    def _normalizeCopiedNodeSelection(self, node_ids: typing.Iterable[int]) -> typing.Tuple[typing.List[int], typing.List[int]]:
        if not self.flow_data.flow or not self.flow_data.flow.flowchart:
            return [], []

        flowchart = self.flow_data.flow.flowchart
        event_indices = {int(idx) for idx in node_ids if int(idx) >= 0}
        entry_rows = self._selectedEntryPointRows(node_ids)
        index_by_event = {event: idx for idx, event in enumerate(flowchart.events)}
        for row in entry_rows:
            entry_point = flowchart.entry_points[row]
            if entry_point.main_event.v in index_by_event:
                event_indices.add(index_by_event[entry_point.main_event.v])
        return sorted(event_indices), entry_rows

    def _serializeSelectedEvents(self, selected_indices: typing.Iterable[int]) -> typing.Dict[str, typing.Any]:
        assert self.flow_data.flow and self.flow_data.flow.flowchart
        events = self.flow_data.flow.flowchart.events
        expanded_indices = self._expandCopySelection(selected_indices)
        included = set(expanded_indices)
        index_by_event = {event: idx for idx, event in enumerate(events)}
        actor_payloads: typing.Dict[typing.Tuple[str, str], typing.Dict[str, typing.Any]] = {}
        event_payloads = []

        def serialize_ref(target: typing.Optional[Event]) -> typing.Optional[int]:
            if not target:
                return None
            idx = index_by_event.get(target)
            return idx if idx in included else None

        for idx in expanded_indices:
            event = events[idx]
            record: typing.Dict[str, typing.Any] = {
                'source_idx': idx,
                'kind': '',
            }

            if isinstance(event.data, ActionEvent):
                actor = event.data.actor.v
                actor_key = (actor.identifier.name, actor.identifier.sub_name)
                actor_payloads.setdefault(actor_key, self._serializeActor(actor))
                record.update({
                    'kind': 'action',
                    'actor_key': actor_key,
                    'actor_action': event.data.actor_action.v.v,
                    'params': self._cloneContainerData(event.data.params),
                    'nxt': serialize_ref(event.data.nxt.v),
                })
            elif isinstance(event.data, SwitchEvent):
                actor = event.data.actor.v
                actor_key = (actor.identifier.name, actor.identifier.sub_name)
                actor_payloads.setdefault(actor_key, self._serializeActor(actor))
                record.update({
                    'kind': 'switch',
                    'actor_key': actor_key,
                    'actor_query': event.data.actor_query.v.v,
                    'params': self._cloneContainerData(event.data.params),
                    'cases': [
                        {'value': int(value), 'target': serialize_ref(case.v)}
                        for value, case in event.data.cases.items()
                        if serialize_ref(case.v) is not None
                    ],
                })
            elif isinstance(event.data, ForkEvent):
                record.update({
                    'kind': 'fork',
                    'join': serialize_ref(event.data.join.v),
                    'forks': [serialize_ref(fork.v) for fork in event.data.forks if serialize_ref(fork.v) is not None],
                })
            elif isinstance(event.data, JoinEvent):
                record.update({
                    'kind': 'join',
                    'nxt': serialize_ref(event.data.nxt.v),
                })
            elif isinstance(event.data, SubFlowEvent):
                record.update({
                    'kind': 'sub_flow',
                    'params': self._cloneContainerData(event.data.params),
                    'res_flowchart_name': event.data.res_flowchart_name,
                    'entry_point_name': event.data.entry_point_name,
                    'nxt': serialize_ref(event.data.nxt.v),
                })
            else:
                continue

            event_payloads.append(record)

        return {
            'version': 2,
            'events': event_payloads,
            'actors': list(actor_payloads.values()),
        }

    def _serializeSelectedEntryPoints(self, entry_rows: typing.Iterable[int],
                                      included_event_indices: typing.Set[int]) -> typing.List[typing.Dict[str, typing.Any]]:
        assert self.flow_data.flow and self.flow_data.flow.flowchart
        flowchart = self.flow_data.flow.flowchart
        index_by_event = {event: idx for idx, event in enumerate(flowchart.events)}
        payloads: typing.List[typing.Dict[str, typing.Any]] = []

        for row in entry_rows:
            if not (0 <= row < len(flowchart.entry_points)):
                continue
            entry_point = flowchart.entry_points[row]
            main_event = entry_point.main_event.v
            main_event_idx = index_by_event.get(main_event)
            payloads.append({
                'name': entry_point.name,
                'items': self._copyEntryPointItems(entry_point),
                'main_event_idx': main_event_idx if main_event_idx in included_event_indices else None,
                'main_event_name': main_event.name if main_event else '',
            })
        return payloads

    def _writeClipboardPayload(self, payload: typing.Dict[str, typing.Any]) -> None:
        encoded = base64.b64encode(pickle.dumps(payload, protocol=4)).decode('ascii')
        q.QApplication.clipboard().setText(EVENT_CLIPBOARD_PREFIX + encoded)

    def _readClipboardPayload(self) -> typing.Optional[typing.Dict[str, typing.Any]]:
        text = q.QApplication.clipboard().text()
        if not text.startswith(EVENT_CLIPBOARD_PREFIX):
            return None
        try:
            payload = pickle.loads(base64.b64decode(text[len(EVENT_CLIPBOARD_PREFIX):]))
        except Exception:
            return None
        if not isinstance(payload, dict) or payload.get('version') not in (1, 2):
            return None
        return payload

    def webCopyEvents(self, indices: typing.List[int]) -> None:
        if not self.flow_data.flow or not self.flow_data.flow.flowchart:
            return
        event_indices, entry_rows = self._normalizeCopiedNodeSelection(indices)
        if not event_indices and not entry_rows:
            q.QMessageBox.information(self, 'Copy events', 'Please select at least one event or entry point node to copy.')
            return

        payload = self._serializeSelectedEvents(event_indices)
        payload['entry_points'] = self._serializeSelectedEntryPoints(
            entry_rows,
            {record['source_idx'] for record in payload.get('events', [])},
        )
        if not payload['events'] and not payload['entry_points']:
            q.QMessageBox.information(self, 'Copy events', 'No event or entry point nodes were copied.')
            return
        self._writeClipboardPayload(payload)

    def _ensureActorFromPayload(self, actor_payload: typing.Dict[str, typing.Any]) -> typing.Tuple[Actor, bool]:
        assert self.flow_data.flow and self.flow_data.flow.flowchart
        identifier_name, identifier_sub_name = actor_payload['identifier']
        actor = next((a for a in self.flow_data.flow.flowchart.actors
                      if a.identifier.name == identifier_name and a.identifier.sub_name == identifier_sub_name), None)
        changed = False
        if actor is None:
            actor = Actor()
            actor.identifier.name = identifier_name
            actor.identifier.sub_name = identifier_sub_name
            actor.argument_name = actor_payload.get('argument_name', '')
            actor.concurrent_clips = actor_payload.get('concurrent_clips', 0xFFFF)
            actor.actions = [StringHolder(name) for name in actor_payload.get('actions', [])]
            actor.queries = [StringHolder(name) for name in actor_payload.get('queries', [])]
            actor.params = self._makeContainerFromData(actor_payload.get('params'))
            self.flow_data.flow.flowchart.actors.append(actor)
            changed = True
        else:
            existing_actions = {action.v for action in actor.actions}
            for action_name in actor_payload.get('actions', []):
                if action_name not in existing_actions:
                    actor.actions.append(StringHolder(action_name))
                    existing_actions.add(action_name)
                    changed = True
            existing_queries = {query.v for query in actor.queries}
            for query_name in actor_payload.get('queries', []):
                if query_name not in existing_queries:
                    actor.queries.append(StringHolder(query_name))
                    existing_queries.add(query_name)
                    changed = True
            if actor.params is None and actor_payload.get('params') is not None:
                actor.params = self._makeContainerFromData(actor_payload.get('params'))
                changed = True

        return actor, changed

    def _ensureActorString(self, values: typing.List[StringHolder], value: str) -> StringHolder:
        for item in values:
            if item.v == value:
                return item
        new_value = StringHolder(value)
        values.append(new_value)
        return new_value

    def _instantiatePastedEvent(self, record: typing.Dict[str, typing.Any],
                                actors: typing.Dict[typing.Tuple[str, str], Actor]) -> Event:
        event = Event()
        event.name = self.flow_data.generateEventName()
        kind = record['kind']

        if kind == 'action':
            event.data = ActionEvent()
            actor = actors[tuple(record['actor_key'])]
            event.data.actor.v = actor
            event.data.actor_action.v = self._ensureActorString(actor.actions, record['actor_action'])
            event.data.params = self._makeContainerFromData(record.get('params'))
        elif kind == 'switch':
            event.data = SwitchEvent()
            actor = actors[tuple(record['actor_key'])]
            event.data.actor.v = actor
            event.data.actor_query.v = self._ensureActorString(actor.queries, record['actor_query'])
            event.data.params = self._makeContainerFromData(record.get('params'))
        elif kind == 'fork':
            event.data = ForkEvent()
        elif kind == 'join':
            event.data = JoinEvent()
        elif kind == 'sub_flow':
            event.data = SubFlowEvent()
            event.data.params = self._makeContainerFromData(record.get('params'))
            event.data.res_flowchart_name = record['res_flowchart_name']
            event.data.entry_point_name = record['entry_point_name']
        else:
            raise ValueError(f'Unsupported clipboard event type: {kind}')

        return event

    def _applyPastedConnections(self, event: Event, record: typing.Dict[str, typing.Any],
                                event_map: typing.Dict[int, Event]) -> None:
        if isinstance(event.data, ActionEvent):
            event.data.nxt.v = event_map.get(record.get('nxt'))
        elif isinstance(event.data, SwitchEvent):
            event.data.cases = {}
            for case in record.get('cases', []):
                target = event_map.get(case.get('target'))
                if not target:
                    continue
                required_index: RequiredIndex[Event] = RequiredIndex()
                required_index.v = target
                event.data.cases[int(case['value'])] = required_index
        elif isinstance(event.data, ForkEvent):
            join_event = event_map.get(record.get('join'))
            if not join_event:
                raise ValueError('Clipboard fork event is missing its join event.')
            event.data.join.v = join_event
            event.data.forks = []
            for target_idx in record.get('forks', []):
                target = event_map.get(target_idx)
                if not target:
                    continue
                required_index: RequiredIndex[Event] = RequiredIndex()
                required_index.v = target
                event.data.forks.append(required_index)
            if not event.data.forks:
                raise ValueError('Clipboard fork event is missing its fork branches.')
        elif isinstance(event.data, JoinEvent):
            event.data.nxt.v = event_map.get(record.get('nxt'))
        elif isinstance(event.data, SubFlowEvent):
            event.data.nxt.v = event_map.get(record.get('nxt'))

    def _replaceEventDataFromClipboard(self, target_event: Event, record: typing.Dict[str, typing.Any],
                                       actors: typing.Dict[typing.Tuple[str, str], Actor]) -> None:
        source_kind = record['kind']
        current_data = target_event.data

        if source_kind == 'action':
            if not isinstance(current_data, (ActionEvent, SubFlowEvent)):
                raise ValueError('A copied action event can only be pasted over an action or sub flow event.')
            next_event = current_data.nxt.v
            new_data = ActionEvent()
            actor = actors[tuple(record['actor_key'])]
            new_data.actor.v = actor
            new_data.actor_action.v = self._ensureActorString(actor.actions, record['actor_action'])
            new_data.params = self._makeContainerFromData(record.get('params'))
            new_data.nxt.v = next_event
            target_event.data = new_data
            return

        if source_kind == 'sub_flow':
            if not isinstance(current_data, (ActionEvent, SubFlowEvent)):
                raise ValueError('A copied sub flow event can only be pasted over an action or sub flow event.')
            next_event = current_data.nxt.v
            new_data = SubFlowEvent()
            new_data.params = self._makeContainerFromData(record.get('params'))
            new_data.res_flowchart_name = record['res_flowchart_name']
            new_data.entry_point_name = record['entry_point_name']
            new_data.nxt.v = next_event
            target_event.data = new_data
            return

        if source_kind == 'switch':
            if not isinstance(current_data, SwitchEvent):
                raise ValueError('A copied switch event can only be pasted over another switch event.')
            new_data = SwitchEvent()
            actor = actors[tuple(record['actor_key'])]
            new_data.actor.v = actor
            new_data.actor_query.v = self._ensureActorString(actor.queries, record['actor_query'])
            new_data.params = self._makeContainerFromData(record.get('params'))
            new_data.cases = current_data.cases
            target_event.data = new_data
            return

        if source_kind == 'join':
            if not isinstance(current_data, JoinEvent):
                raise ValueError('A copied join event can only be pasted over another join event.')
            new_data = JoinEvent()
            new_data.nxt.v = current_data.nxt.v
            target_event.data = new_data
            return

        if source_kind == 'fork':
            if not isinstance(current_data, ForkEvent):
                raise ValueError('A copied fork event can only be pasted over another fork event.')
            new_data = ForkEvent()
            new_data.join.v = current_data.join.v
            new_data.forks = current_data.forks
            target_event.data = new_data
            return

        raise ValueError(f'Unsupported clipboard event type: {source_kind}')

    def _makeUniqueEntryPointName(self, base_name: str) -> str:
        assert self.flow_data.flow and self.flow_data.flow.flowchart
        existing_names = {entry_point.name for entry_point in self.flow_data.flow.flowchart.entry_points}
        if base_name not in existing_names:
            return base_name
        suffix = 1
        while True:
            candidate = f'{base_name} ({suffix})'
            if candidate not in existing_names:
                return candidate
            suffix += 1

    def _resolveClipboardEntryPointTarget(self, entry_payload: typing.Dict[str, typing.Any],
                                          event_map: typing.Dict[int, Event]) -> typing.Optional[Event]:
        target = event_map.get(entry_payload.get('main_event_idx'))
        if target:
            return target
        main_event_name = entry_payload.get('main_event_name', '')
        if not main_event_name or not self.flow_data.flow or not self.flow_data.flow.flowchart:
            return None
        return next(
            (event for event in self.flow_data.flow.flowchart.events if event.name == main_event_name),
            None,
        )

    def _pastePayload(self, payload: typing.Dict[str, typing.Any], target_idx: typing.Optional[int] = None,
                      reveal_new_events: bool = False, action_name: str = 'Paste events') -> None:
        if not self.flow_data.flow or not self.flow_data.flow.flowchart:
            return
        flowchart = self.flow_data.flow.flowchart
        actors_by_key: typing.Dict[typing.Tuple[str, str], Actor] = {}
        actor_model_changed = False
        created_events: typing.List[Event] = []
        created_entry_points: typing.List[EntryPoint] = []
        appended_events = False
        try:
            for actor_payload in payload.get('actors', []):
                actor, changed = self._ensureActorFromPayload(actor_payload)
                actors_by_key[tuple(actor_payload['identifier'])] = actor
                actor_model_changed = actor_model_changed or changed

            records = payload.get('events', [])
            entry_point_records = payload.get('entry_points', [])
            if target_idx is not None and len(records) == 1 and not entry_point_records and 0 <= target_idx < len(flowchart.events):
                self._replaceEventDataFromClipboard(flowchart.events[target_idx], records[0], actors_by_key)
                if actor_model_changed:
                    self.flow_data.actor_model.set(self.flow_data.flow)
                self.selected_event = flowchart.events[target_idx]
                self.pending_reveal_event = None
                self.suppress_reload_reselect = True
                self.web_object.preserveViewportRequested.emit()
                self.flow_data.event_model.set(self.flow_data.flow)
                reason = FlowDataChangeReason.Events
                if actor_model_changed:
                    reason |= FlowDataChangeReason.Actors
                self.flow_data.flowDataChanged.emit(reason)
                return

            event_map: typing.Dict[int, Event] = {}
            for record in records:
                event = self._instantiatePastedEvent(record, actors_by_key)
                created_events.append(event)
                event_map[int(record['source_idx'])] = event

            flowchart.events.extend(created_events)
            appended_events = True

            for record in records:
                self._applyPastedConnections(event_map[int(record['source_idx'])], record, event_map)

            for entry_payload in entry_point_records:
                target_event = self._resolveClipboardEntryPointTarget(entry_payload, event_map)
                if not target_event:
                    continue
                entry_point = EntryPoint(self._makeUniqueEntryPointName(entry_payload['name']))
                entry_point.main_event.v = target_event
                self._setEntryPointItems(entry_point, entry_payload.get('items', {}))
                flowchart.entry_points.append(entry_point)
                created_entry_points.append(entry_point)
        except Exception as exc:
            if appended_events and created_events:
                del flowchart.events[-len(created_events):]
            if created_entry_points:
                del flowchart.entry_points[-len(created_entry_points):]
            traceback.print_exc()
            q.QMessageBox.critical(self, action_name, f'Failed to apply clipboard data.\n\n{exc}')
            return

        if actor_model_changed:
            self.flow_data.actor_model.set(self.flow_data.flow)
        if created_entry_points:
            self.flow_data.entry_point_model.set(self.flow_data.flow)

        if not created_events and not created_entry_points:
            q.QMessageBox.information(self, action_name, 'No events or entry points could be created from the provided data.')
            return

        self.selected_event = None
        self.selected_node_id = None
        self.pending_reveal_event = created_events[0] if (reveal_new_events and created_events) else None
        self.container_model.set(None)
        self.container_stacked_widget.setCurrentIndex(0)
        if not self.pending_reveal_event:
            self.web_object.preserveViewportRequested.emit()
        self.flow_data.event_model.set(self.flow_data.flow)
        reason = FlowDataChangeReason.Events
        if actor_model_changed:
            reason |= FlowDataChangeReason.Actors
        self.flow_data.flowDataChanged.emit(reason)

    def webPasteEvents(self, target_idx: typing.Optional[int] = None, reveal_new_events: bool = False) -> None:
        payload = self._readClipboardPayload()
        if not payload:
            q.QMessageBox.information(self, 'Paste events', 'No compatible EventEditor clipboard data was found.')
            return
        self._pastePayload(payload, target_idx=target_idx, reveal_new_events=reveal_new_events, action_name='Paste events')

    def _entryPointParentsForEvent(self, event: Event) -> typing.List[EntryPoint]:
        assert self.flow_data.flow and self.flow_data.flow.flowchart
        return [entry_point for entry_point in self.flow_data.flow.flowchart.entry_points
                if entry_point.main_event.v == event]

    def _selectedForkRoots(self, selected_indices: typing.Iterable[int]) -> typing.List[int]:
        if not self.flow_data.flow or not self.flow_data.flow.flowchart:
            return []

        events = self.flow_data.flow.flowchart.events
        selected_set = {idx for idx in selected_indices if 0 <= idx < len(events)}
        roots: typing.List[int] = []
        covered: typing.Set[int] = set()
        for idx in sorted(selected_set):
            if idx in covered:
                continue
            event = events[idx]
            if not isinstance(event.data, ForkEvent):
                continue
            structure = set(self._expandCopySelection([idx]))
            if structure.issubset(selected_set):
                roots.append(idx)
                covered.update(structure)
        return roots

    def _doRemoveForkStructure(self, fork_idx: int, show_error: bool = True) -> bool:
        assert self.flow_data.flow and self.flow_data.flow.flowchart
        events = self.flow_data.flow.flowchart.events
        if not (0 <= fork_idx < len(events)):
            return False

        fork_event = events[fork_idx]
        if fork_event is None or not isinstance(fork_event.data, ForkEvent):
            return False

        structure_indices = self._expandCopySelection([fork_idx])
        structure_events = {
            events[idx] for idx in structure_indices
            if 0 <= idx < len(events) and events[idx] is not None
        }
        join_event = fork_event.data.join.v
        next_event = join_event.data.nxt.v if isinstance(join_event.data, JoinEvent) else None

        parents = [parent for parent, branches in self._findEventParentNodes(fork_event)]
        if len(parents) == 1 and isinstance(parents[0].data, ForkEvent) and len(parents[0].data.forks) == 1 and not next_event:
            if show_error:
                q.QMessageBox.information(self, 'Cannot delete', 'Please delete the parent fork event first.')
            return False

        for parent in parents:
            if isinstance(parent.data, (ActionEvent, JoinEvent, SubFlowEvent)):
                parent.data.nxt.v = next_event
            elif isinstance(parent.data, SwitchEvent):
                for case in list(parent.data.cases.keys()):
                    if parent.data.cases[case].v == fork_event:
                        if next_event:
                            parent.data.cases[case].v = next_event
                        else:
                            del parent.data.cases[case]
            elif isinstance(parent.data, ForkEvent):
                new_forks = []
                for fork in parent.data.forks:
                    if fork.v != fork_event:
                        new_forks.append(fork)
                    elif next_event:
                        ri: RequiredIndex[Event] = RequiredIndex()
                        ri.v = next_event
                        new_forks.append(ri)
                parent.data.forks = new_forks

        for entry_point in self.flow_data.flow.flowchart.entry_points:
            if entry_point.main_event.v in structure_events:
                entry_point.main_event.v = next_event

        for idx in structure_indices:
            if 0 <= idx < len(events):
                events[idx] = None # type: ignore
        return True

    def _descendantsRemovedBySelectedForks(self, selected_indices: typing.Iterable[int]) -> typing.Set[int]:
        if not self.flow_data.flow or not self.flow_data.flow.flowchart:
            return set()

        events = self.flow_data.flow.flowchart.events
        descendants: typing.Set[int] = set()
        for idx in selected_indices:
            if not (0 <= idx < len(events)):
                continue
            event = events[idx]
            if not isinstance(event.data, ForkEvent):
                continue
            fork_structure = set(self._expandCopySelection([idx]))
            fork_structure.discard(idx)
            descendants.update(fork_structure)
        return descendants

    def _canRemoveEvent(self, event: Event) -> bool:
        next_event: typing.Optional[Event] = None
        if isinstance(event.data, (ActionEvent, JoinEvent, SubFlowEvent)):
            next_event = event.data.nxt.v
        elif isinstance(event.data, SwitchEvent):
            if len(event.data.cases) > 1:
                return False
            next_event = next(iter(event.data.cases.values())).v if event.data.cases else None
        elif isinstance(event.data, ForkEvent):
            if len(event.data.forks) > 1:
                return False
            next_event = event.data.forks[0].v if event.data.forks else None
        else:
            return False

        event_parents = self._findEventParentNodes(event)
        entry_parents = self._entryPointParentsForEvent(event)
        is_only_event_in_entry = next_event is None and len(event_parents) == 0 and len(entry_parents) == 1
        return not is_only_event_in_entry

    def webRemoveEvents(self, indices: typing.List[int]) -> None:
        if not self.flow_data.flow or not self.flow_data.flow.flowchart:
            return

        entry_rows = sorted(set(self._selectedEntryPointRows(indices)), reverse=True)
        selected_indices = sorted(set(idx for idx in indices if idx >= 0), reverse=True)
        if not selected_indices and not entry_rows:
            return
        if not selected_indices and entry_rows:
            self.selected_event = None
            self.selected_node_id = None
            self.container_model.set(None)
            self.container_stacked_widget.setCurrentIndex(0)
            for row in entry_rows:
                if 0 <= row < len(self.flow_data.flow.flowchart.entry_points):
                    self.flow_data.flow.flowchart.entry_points.pop(row)
            self.web_object.preserveViewportRequested.emit()
            self.flow_data.entry_point_model.set(self.flow_data.flow)
            self.flow_data.flowDataChanged.emit(FlowDataChangeReason.Events)
            return
        if len(selected_indices) == 1:
            idx = selected_indices[0]
            event = self.flow_data.flow.flowchart.events[idx]
            parents = [self.flow_data.flow.flowchart.events.index(parent)
                       for parent, branches in self._findEventParentNodes(event)]
            self.webRemoveEvent(parents, idx)
            if entry_rows:
                for row in entry_rows:
                    if 0 <= row < len(self.flow_data.flow.flowchart.entry_points):
                        self.flow_data.flow.flowchart.entry_points.pop(row)
                self.flow_data.entry_point_model.set(self.flow_data.flow)
                self.web_object.preserveViewportRequested.emit()
                self.flow_data.flowDataChanged.emit(FlowDataChangeReason.Events)
            return

        events = self.flow_data.flow.flowchart.events
        skipped_names: typing.List[str] = []
        remaining = list(selected_indices)
        deleted_any = False
        selected_fork_roots = set(self._selectedForkRoots(selected_indices))

        while remaining:
            progress = False
            next_remaining: typing.List[int] = []
            for idx in remaining:
                if idx >= len(events):
                    progress = True
                    continue

                event = events[idx]
                if event is None:
                    progress = True
                    continue

                if idx in selected_fork_roots and isinstance(event.data, ForkEvent):
                    if self._doRemoveForkStructure(idx, show_error=False):
                        progress = True
                        deleted_any = True
                    else:
                        next_remaining.append(idx)
                    continue

                parents = [parent for parent, branches in self._findEventParentNodes(event)]
                if self._doRemoveEvent(parents, idx, show_error=False):
                    progress = True
                    deleted_any = True
                else:
                    next_remaining.append(idx)

            if not progress:
                skipped_names.extend(
                    events[idx].name for idx in next_remaining
                    if 0 <= idx < len(events) and events[idx] is not None
                )
                break

            remaining = next_remaining

        if not deleted_any:
            if skipped_names:
                q.QMessageBox.information(
                    self,
                    'Delete selected events',
                    'None of the selected events can be deleted safely.'
                )
            return

        self.selected_event = None
        self.selected_node_id = None
        self.container_model.set(None)
        self.container_stacked_widget.setCurrentIndex(0)

        self.flow_data.flow.flowchart.events = [
            event for event in self.flow_data.flow.flowchart.events if event is not None
        ]
        for row in entry_rows:
            if 0 <= row < len(self.flow_data.flow.flowchart.entry_points):
                self.flow_data.flow.flowchart.entry_points.pop(row)
        self.web_object.preserveViewportRequested.emit()
        self.flow_data.event_model.set(self.flow_data.flow)
        self.flow_data.entry_point_model.set(self.flow_data.flow)
        self.flow_data.flowDataChanged.emit(FlowDataChangeReason.Events)

        if skipped_names:
            q.QMessageBox.information(
                self,
                'Delete selected events',
                'Some selected events were skipped because deleting them would break the graph:\n\n' + '\n'.join(skipped_names[:20])
            )

    def createNewEvent(self) -> typing.Optional[Event]:
        return add_new_event(self, self.flow_data)

    def addNewEvent(self) -> typing.Optional[Event]:
        new_event = self.createNewEvent()
        if not new_event:
            return None
        self.flow_data.flowDataChanged.emit(FlowDataChangeReason.Events)
        self.delayedSelect(new_event)
        return new_event

    def webAddEventAbove(self, parent_indices: typing.List[int], event_idx: int) -> None:
        if event_idx < 0:
            return
        assert self.flow_data.flow and self.flow_data.flow.flowchart
        event = self.flow_data.flow.flowchart.events[event_idx]

        parent_events = [self.flow_data.flow.flowchart.events[i] for i in parent_indices if i >= 0]
        list_widget = CheckableEventParentListWidget(None, event, parent_events)
        if parent_events:
            dialog = q.QDialog(self, qc.Qt.WindowTitleHint | qc.Qt.WindowSystemMenuHint)
            dialog.setWindowTitle('Add new event above...')
            btn_box = q.QDialogButtonBox(q.QDialogButtonBox.Ok | q.QDialogButtonBox.Cancel);
            btn_box.accepted.connect(dialog.accept)
            btn_box.rejected.connect(dialog.reject)
            dialog_layout = q.QVBoxLayout(dialog)
            dialog_layout.addWidget(q.QLabel('Please select links that should be modified to point to the new event you are going to add.'))
            dialog_layout.addWidget(list_widget)
            dialog_layout.addWidget(btn_box)
            ret = dialog.exec_()
            if not ret:
                return

        new_parent = self.createNewEvent()
        if not new_parent:
            return

        self._doAddEventAbove(list_widget.getSelectedEvents(), event, new_parent)
        self.flow_data.flowDataChanged.emit(FlowDataChangeReason.Events)
        self.delayedSelect(new_parent)

    def _doAddEventAbove(self, parents: typing.List[typing.Tuple[Event, typing.List[typing.Any]]], event: Event, new_parent: Event) -> None:
        # Update the parents to point to the new parent.
        for parent, branches in parents:
            if isinstance(parent.data, ActionEvent) or isinstance(parent.data, JoinEvent) or isinstance(parent.data, SubFlowEvent):
                # Easy case: just set the next pointer to the new parent.
                parent.data.nxt.v = new_parent

            # For switch and fork events, update all branches that currently point to the event.
            elif isinstance(parent.data, SwitchEvent):
                for case in branches:
                    if parent.data.cases[case].v == event:
                        parent.data.cases[case].v = new_parent
            elif isinstance(parent.data, ForkEvent):
                for i, fork in enumerate(branches):
                    if fork.v == event:
                        parent.data.forks[i].v = new_parent

        # Make the new parent point to the event.
        if isinstance(new_parent.data, ActionEvent):
            new_parent.data.nxt.v = event
        elif isinstance(new_parent.data, SwitchEvent):
            new_parent.data.cases[-1] = RequiredIndex()
            new_parent.data.cases[-1].v = event
        elif isinstance(new_parent.data, SubFlowEvent):
            new_parent.data.nxt.v = event
        elif isinstance(new_parent.data, ForkEvent):
            new_parent.data.forks.clear()
            ri: RequiredIndex[Event] = RequiredIndex()
            ri.v = event
            new_parent.data.forks.append(ri)

    def webAddEventBelow(self, event_idx: int) -> None:
        if event_idx < 0:
            return
        assert self.flow_data.flow and self.flow_data.flow.flowchart
        event = self.flow_data.flow.flowchart.events[event_idx]
        new_event = self.createNewEvent()
        if new_event:
            self.webDoAddEventBelow(event, new_event)

    def webDoAddEventBelow(self, event: Event, target: Event) -> None:
        if not (isinstance(event.data, ActionEvent) or isinstance(event.data, SubFlowEvent) or isinstance(event.data, JoinEvent)):
            return

        if isinstance(target.data, ActionEvent):
            target.data.nxt.v = event.data.nxt.v
        elif isinstance(target.data, SwitchEvent):
            if event.data.nxt.v:
                target.data.cases[-1] = RequiredIndex()
                target.data.cases[-1].v = event.data.nxt.v
        elif isinstance(target.data, SubFlowEvent):
            target.data.nxt.v = event.data.nxt.v

        event.data.nxt.v = target

        self.flow_data.flowDataChanged.emit(FlowDataChangeReason.Events)
        self.delayedSelect(target)

    def webLink(self, event_idx: int) -> None:
        if event_idx < 0:
            return
        assert self.flow_data.flow and self.flow_data.flow.flowchart
        event = self.flow_data.flow.flowchart.events[event_idx]
        self.web_object.actionProhibitionChanged.emit(True)
        dialog = EventChooserDialog(self, self.flow_data)
        dialog.event_view.jumpToFlowchartRequested.connect(self.selectRequested)
        self.eventSelected.connect(dialog.event_view.selectEvent)
        dialog.accepted.connect(lambda: self.webDoLink(event, dialog.getSelectedEvent()))
        dialog.finished.connect(lambda: self.web_object.actionProhibitionChanged.emit(False))
        dialog.show()

    def webDoLink(self, event: Event, target: Event) -> None:
        if event == target:
            q.QMessageBox.critical(self, 'Invalid choice', 'Cannot link an event to itself. Please choose another event and try again.')
            return
        event.data.nxt.v = target # type: ignore
        self.flow_data.flowDataChanged.emit(FlowDataChangeReason.Events)
        self.delayedSelect(target)

    def webUnlink(self, event_idx: int) -> None:
        ret = q.QMessageBox.question(self, 'Unlink', 'Warning: Unlinking events that are in nested fork branches can currently result in graph corruption. Continue?')
        if ret != q.QMessageBox.Yes:
            return

        assert self.flow_data.flow and self.flow_data.flow.flowchart
        event = self.flow_data.flow.flowchart.events[event_idx]
        event.data.nxt.v = None # type: ignore
        self.flow_data.flowDataChanged.emit(FlowDataChangeReason.Events)
        self.delayedSelect(event)

    def _findForkEventLeafNodes(self, starting_event: Event) -> typing.List[Event]:
        assert isinstance(starting_event.data, ForkEvent)
        parents: typing.List[Event] = []
        visited: typing.Set[Event] = set()

        def handleNextEvent(event: Event, next_event: typing.Optional[Event], join_stack: typing.List[Event]) -> None:
            if not next_event:
                if not join_stack:
                    parents.append(event)
                return
            traverse(next_event, join_stack)

        def traverse(event: Event, join_stack: typing.List[Event]) -> None:
            if event in visited:
                return
            visited.add(event)
            data = event.data
            if isinstance(data, ActionEvent):
                handleNextEvent(event, data.nxt.v, join_stack)
            elif isinstance(data, SwitchEvent):
                for value, case in data.cases.items():
                    traverse(case.v, join_stack)
            elif isinstance(data, ForkEvent):
                join_stack.append(data.join.v)
                for fork in data.forks:
                    traverse(fork.v, join_stack)
                traverse(data.join.v, join_stack)
            elif isinstance(data, JoinEvent):
                join_stack.pop()
                handleNextEvent(event, data.nxt.v, join_stack)
            elif isinstance(data, SubFlowEvent):
                handleNextEvent(event, data.nxt.v, join_stack)

        for fork in starting_event.data.forks:
            traverse(fork.v, [])
        return parents

    def _doRemoveEvent(self, parents: typing.List[Event], event_idx: int, show_error: bool = True) -> bool:
        """Erase an event from the tree, ensuring that the next pointers of parents are updated.

        This does not resize the event list. None items must be removed from the list afterwards."""
        assert self.flow_data.flow and self.flow_data.flow.flowchart
        event = self.flow_data.flow.flowchart.events[event_idx]

        next_event: typing.Optional[Event] = None
        if isinstance(event.data, ActionEvent) or isinstance(event.data, JoinEvent) or isinstance(event.data, SubFlowEvent):
            next_event = event.data.nxt.v
        elif isinstance(event.data, SwitchEvent):
            next_event = next(iter(event.data.cases.values())).v if event.data.cases else None
        elif isinstance(event.data, ForkEvent):
            if len(event.data.forks) != 1:
                return False
            next_event = event.data.forks[0].v

        # Don't let the user delete the only branch in a fork event
        if len(parents) == 1 and isinstance(parents[0].data, ForkEvent) and len(parents[0].data.forks) == 1 and not next_event:
            if show_error:
                q.QMessageBox.information(self, 'Cannot delete', 'Please delete the parent fork event first.')
            return False

        # Make the parents point to the next event.
        for parent in parents:
            if isinstance(parent.data, ActionEvent) or isinstance(parent.data, JoinEvent) or isinstance(parent.data, SubFlowEvent):
                parent.data.nxt.v = next_event

            # For switch and fork events, update all branches that currently point to the event.
            # Or remove them if there is no next event.
            elif isinstance(parent.data, SwitchEvent):
                for case in list(parent.data.cases.keys()):
                    if parent.data.cases[case].v == event:
                        if next_event:
                            parent.data.cases[case].v = next_event
                        else:
                            del parent.data.cases[case]
            elif isinstance(parent.data, ForkEvent):
                new_forks = []
                for fork in parent.data.forks:
                    if fork.v != event:
                        new_forks.append(fork)
                    elif next_event:
                        ri: RequiredIndex[Event] = RequiredIndex()
                        ri.v = next_event
                        new_forks.append(ri)
                parent.data.forks = new_forks

        # If we are removing a fork event, also remove the associated join.
        if isinstance(event.data, ForkEvent):
            self._doRemoveEvent(
                self._findForkEventLeafNodes(event),
                self.flow_data.flow.flowchart.events.index(event.data.join.v),
                show_error=show_error,
            )

        # Ensure that entry points point to the correct event.
        for entry_point in self.flow_data.flow.flowchart.entry_points:
            if entry_point.main_event.v == event:
                entry_point.main_event.v = next_event

        # Erase this event from the list. None elements will be swept by the caller.
        self.flow_data.flow.flowchart.events[event_idx] = None # type: ignore
        return True

    def webRemoveEvent(self, parent_indices: typing.List[int], event_idx: int) -> None:
        if event_idx < 0:
            return
        assert self.flow_data.flow and self.flow_data.flow.flowchart

        self.selected_event = None
        self.selected_node_id = None
        self.container_model.set(None)
        self.container_stacked_widget.setCurrentIndex(0)

        parents = [self.flow_data.flow.flowchart.events[idx] for idx in parent_indices if idx >= 0]
        if not self._doRemoveEvent(parents, event_idx):
            return
        self.flow_data.flow.flowchart.events = \
            [event for event in self.flow_data.flow.flowchart.events if event is not None]
        # Since we're editing the array directly, a model reset MUST be triggered.
        self.web_object.preserveViewportRequested.emit()
        self.flow_data.event_model.set(self.flow_data.flow)

        self.flow_data.flowDataChanged.emit(FlowDataChangeReason.Events)

    def webEditSwitchBranches(self, event_idx: int) -> None:
        if event_idx < 0:
            return
        assert self.flow_data.flow and self.flow_data.flow.flowchart
        event = self.flow_data.flow.flowchart.events[event_idx]
        if not isinstance(event.data, SwitchEvent):
            return
        self.web_object.actionProhibitionChanged.emit(True)
        dialog = SwitchEventEditDialog(self, event.data.cases, self.flow_data)
        dialog.chooserEventDoubleClicked.connect(self.selectRequested)
        self.eventSelected.connect(dialog.chooserSelectSignal)
        self._keepDialogOpen(dialog)
        def cleanup(*args) -> None:
            try:
                self.eventSelected.disconnect(dialog.chooserSelectSignal)
            except TypeError:
                pass
            self.web_object.actionProhibitionChanged.emit(False)
        dialog.finished.connect(cleanup)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def webEditForkBranches(self, event_idx: int) -> None:
        if event_idx < 0:
            return
        assert self.flow_data.flow and self.flow_data.flow.flowchart
        event = self.flow_data.flow.flowchart.events[event_idx]
        if not isinstance(event.data, ForkEvent):
            return
        self.web_object.actionProhibitionChanged.emit(True)
        dialog = ForkEventEditDialog(self, event.data.forks, self.flow_data)
        dialog.chooserEventDoubleClicked.connect(self.selectRequested)
        self.eventSelected.connect(dialog.chooserSelectSignal)
        self._keepDialogOpen(dialog)
        def cleanup(*args) -> None:
            try:
                self.eventSelected.disconnect(dialog.chooserSelectSignal)
            except TypeError:
                pass
            self.web_object.actionProhibitionChanged.emit(False)
        dialog.finished.connect(cleanup)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def addFork(self, node_id: typing.Optional[int] = None) -> None:
        self.web_object.actionProhibitionChanged.emit(True)
        dialog = EventForkChooserDialog(self, self.flow_data)
        if node_id is not None and self.flow_data.flow and self.flow_data.flow.flowchart:
            target_event: typing.Optional[Event] = None
            if node_id >= 0 and node_id < len(self.flow_data.flow.flowchart.events):
                target_event = self.flow_data.flow.flowchart.events[node_id]
            elif node_id < 0:
                entry_point_row = -1000 - int(node_id)
                if 0 <= entry_point_row < len(self.flow_data.flow.flowchart.entry_points):
                    target_event = self.flow_data.flow.flowchart.entry_points[entry_point_row].main_event.v
            if target_event:
                dialog.setStartEvent(target_event)
        self._keepDialogOpen(dialog)
        dialog.finished.connect(lambda: self.web_object.actionProhibitionChanged.emit(False))
        dialog.accepted.connect(lambda: self._doAddFork(*dialog.getEventPair()))
        dialog.chooserEventDoubleClicked.connect(self.selectRequested)
        self.eventSelected.connect(dialog.chooserSelectSignal)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _findEventParentNodes(self, event: Event) -> typing.List[typing.Tuple[Event, typing.List[typing.Any]]]:
        parents: typing.List[typing.Tuple[Event, typing.List[typing.Any]]] = []
        for e in self.flow_data.flow.flowchart.events:
            if e is None:
                continue
            data = e.data
            if isinstance(data, ActionEvent) or isinstance(data, JoinEvent) or isinstance(data, SubFlowEvent):
                if data.nxt.v == event:
                    parents.append((e, []))
            elif isinstance(data, SwitchEvent):
                if any(case.v == event for case in data.cases.values()):
                    parents.append((e, list(data.cases.keys())))
            elif isinstance(data, ForkEvent):
                if any(fork.v == event for fork in data.forks):
                    parents.append((e, data.forks))
        return parents

    def _doAddFork(self, start: Event, end: Event) -> None:
        if not (isinstance(end.data, ActionEvent) or isinstance(end.data, SubFlowEvent)):
            q.QMessageBox.critical(self, 'Not implemented', 'The end event must be an action or sub flow event currently')
            return

        assert self.flow_data.flow and self.flow_data.flow.flowchart

        # Add the fork event as a parent.
        fork_event = Event()
        fork_event.name = self.flow_data.generateEventName()
        fork_event.data = ForkEvent()
        # Add the event manually and do NOT send change signals until the join event is added.
        self.flow_data.flow.flowchart.events.append(fork_event)
        self._doAddEventAbove(self._findEventParentNodes(start), start, fork_event)

        # Fix entry points.
        for entry_point in self.flow_data.flow.flowchart.entry_points:
            if entry_point.main_event.v == start:
                entry_point.main_event.v = fork_event

        # Add the join event as a child.
        join_event = Event()
        join_event.name = self.flow_data.generateEventName()
        join_event.data = JoinEvent()
        join_event.data.nxt.v = end.data.nxt.v
        end.data.nxt.v = None
        self.flow_data.flow.flowchart.events.append(join_event)
        fork_event.data.join.v = join_event

        # Trigger a full model reset since we updated the underlying array directly.
        self.pending_reveal_event = fork_event
        self.suppress_reload_reselect = True
        self.flow_data.event_model.set(self.flow_data.flow)
        self.flow_data.flowDataChanged.emit(FlowDataChangeReason.Events)
