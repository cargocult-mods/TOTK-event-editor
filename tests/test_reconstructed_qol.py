import tempfile
import types
import unittest
from pathlib import Path
import struct

from evfl import Container, Event, EventFlow, Flowchart
from evfl.entry_point import EntryPoint
from evfl.event import ActionEvent, SubFlowEvent
import PyQt5.QtCore as qc # type: ignore

from eventeditor.container_model import (
    ContainerModel,
    ContainerModelColumn,
    format_container_display_value,
)
from eventeditor.event_edit_dialog import (
    _format_period_finding,
    _parameter_period_findings,
    _plain_period_finding,
    _parse_parameter_payload,
)
from eventeditor.event_model import EventModel, EventModelColumn
from eventeditor.__main__ import (
    APP_DISPLAY_NAME,
    GITHUB_REPOSITORY_SLUG,
    GITHUB_REPOSITORY_URL,
    available_mals_locale_names,
    build_about_html,
    choose_mals_archive_from_directory,
    current_mals_display_name,
    discover_mals_locale_names,
    find_eventflow_file_in_directory,
    find_filename_flow_name_mismatch,
    find_missing_internal_subflow_calls,
    flow_filename_name_for_path,
    infer_eventflow_mals_dir,
    infer_eventflow_owner_root,
    infer_mals_archive_for_flow_path,
    is_vanilla_romfs_path,
    mals_locale_name_for_path,
    manual_mals_archive_path,
    MALS_MODE_INFERRED,
    MALS_MODE_MANUAL,
    normalize_display_version,
    normalize_flow_save_path,
)
import eventeditor.actor_xml as actor_xml
import eventeditor.container_xml as container_xml
import eventeditor.entry_point_tree_xml as entry_point_tree_xml
import eventeditor._version as versioneer_runtime_config
import eventeditor.mals as mals
import eventeditor.totk_zs as totk_zs
import eventeditor.util as util


class ReconstructedQoLTests(unittest.TestCase):
    def test_public_identity_strings(self):
        self.assertEqual(APP_DISPLAY_NAME, 'TOTK EventEditor')
        self.assertEqual(GITHUB_REPOSITORY_SLUG, 'cargocult-mods/TOTK-event-editor')
        self.assertEqual(GITHUB_REPOSITORY_URL, 'https://github.com/cargocult-mods/TOTK-event-editor')
        self.assertEqual(versioneer_runtime_config.get_config().tag_prefix, 'v')

        about_html = build_about_html('v1.0.0')
        self.assertIn(APP_DISPLAY_NAME, about_html)
        self.assertIn(GITHUB_REPOSITORY_SLUG, about_html)
        self.assertIn(GITHUB_REPOSITORY_URL, about_html)
        self.assertIn('Version: v1.0.0', about_html)
        self.assertNotIn('Revision:', about_html)

    def test_placeholder_versions_are_not_displayed(self):
        self.assertEqual(normalize_display_version('0+unknown'), 'development build')
        self.assertEqual(normalize_display_version('0+unknown.d20260607'), 'development build')
        self.assertEqual(normalize_display_version(None), 'development build')
        self.assertEqual(normalize_display_version('v1.0.0'), 'v1.0.0')

    def test_totk_suffix_helpers(self):
        self.assertEqual(
            normalize_flow_save_path('Demo', 'Compressed TotK flowchart .bfevfl.zs (*)'),
            'Demo.bfevfl.zs',
        )
        self.assertEqual(flow_filename_name_for_path('Demo.bfevfl.zs'), 'Demo')
        self.assertEqual(flow_filename_name_for_path('Demo.evfl.zs'), 'Demo')
        self.assertTrue(totk_zs.is_compressed_path('Demo.bfevfl.zs'))
        self.assertTrue(totk_zs.is_compressed_path('Demo.bfevfl.zstd'))
        self.assertFalse(totk_zs.is_compressed_path('Demo.bfevfl'))

    def test_save_flow_name_match_helpers(self):
        flow = EventFlow()
        flow.name = 'DemoFlow'
        flow.flowchart = Flowchart()
        flow.flowchart.name = 'DemoFlow'

        self.assertIsNone(find_filename_flow_name_mismatch('DemoFlow.bfevfl.zs', flow))
        self.assertEqual(
            find_filename_flow_name_mismatch('OtherName.bfevfl.zs', flow),
            ('OtherName', ['DemoFlow']),
        )

    def test_missing_internal_subflow_helper(self):
        flow = EventFlow()
        flow.name = 'DemoFlow'
        flow.flowchart = Flowchart()
        flow.flowchart.name = 'DemoFlow'

        entry_point = EntryPoint('Talk')
        flow.flowchart.entry_points = [entry_point]

        valid = Event()
        valid.name = 'EventValid'
        valid.data = SubFlowEvent()
        valid.data.entry_point_name = 'Talk'

        missing = Event()
        missing.name = 'EventMissing'
        missing.data = SubFlowEvent()
        missing.data.entry_point_name = 'Missing'

        external = Event()
        external.name = 'EventExternal'
        external.data = SubFlowEvent()
        external.data.res_flowchart_name = 'ExternalFlow'
        external.data.entry_point_name = 'Missing'

        flow.flowchart.events = [valid, missing, external]
        self.assertEqual(
            find_missing_internal_subflow_calls(flow),
            ['EventMissing calls DemoFlow<Missing>'],
        )

    def test_mals_inference_helpers_for_romfs_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'TestMod'
            flow_dir = root / 'romfs' / 'Event' / 'EventFlow'
            mals_dir = root / 'romfs' / 'Mals'
            flow_dir.mkdir(parents=True)
            mals_dir.mkdir(parents=True)
            flow_path = flow_dir / 'Demo.bfevfl.zs'
            preferred = mals_dir / 'USen.Product.110.sarc.zs'
            fallback = mals_dir / 'ZZ.sarc.zs'
            flow_path.write_bytes(b'')
            preferred.write_bytes(b'')
            fallback.write_bytes(b'')

            self.assertEqual(infer_eventflow_owner_root(str(flow_path)), root)
            self.assertEqual(infer_eventflow_mals_dir(str(flow_path)), mals_dir)
            self.assertEqual(choose_mals_archive_from_directory(mals_dir), str(preferred))
            self.assertEqual(infer_mals_archive_for_flow_path(str(flow_path)), str(preferred))

    def test_mals_locale_matching_ignores_product_versions(self):
        with tempfile.TemporaryDirectory() as tmp:
            mals_dir = Path(tmp) / 'Mals'
            mals_dir.mkdir()
            usen_110 = mals_dir / 'USen.Product.110.sarc.zs'
            usen_120 = mals_dir / 'USen.Product.120.sarc.zs'
            eufr = mals_dir / 'EUfr.Product.110.sarc.zs'
            loose = mals_dir / 'USes.sarc.zs'
            unrelated = mals_dir / 'EventFlowMsg_Test.msbt'
            for path in [usen_110, usen_120, eufr, loose, unrelated]:
                path.write_bytes(b'')

            self.assertEqual(mals_locale_name_for_path(usen_110), 'USen')
            self.assertEqual(mals_locale_name_for_path(eufr), 'EUfr')
            self.assertEqual(discover_mals_locale_names(mals_dir), ['EUfr', 'USen', 'USes'])
            self.assertEqual(choose_mals_archive_from_directory(mals_dir, 'EUfr'), str(eufr))
            self.assertEqual(choose_mals_archive_from_directory(mals_dir, 'USen'), str(usen_110))
            self.assertEqual(choose_mals_archive_from_directory(mals_dir, 'JPja'), '')

    def test_manual_mals_locale_selection_uses_manual_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            mals_dir = Path(tmp) / 'Mals'
            mals_dir.mkdir()
            usen = mals_dir / 'USen.Product.110.sarc.zs'
            jpja = mals_dir / 'JPja.Product.110.sarc.zs'
            direct_msbt = mals_dir / 'CC_Test.msbt'
            for path in [usen, jpja, direct_msbt]:
                path.write_bytes(b'')

            self.assertEqual(manual_mals_archive_path(str(usen), 'JPja'), str(jpja))
            self.assertEqual(manual_mals_archive_path(str(direct_msbt), 'JPja'), str(direct_msbt))

    def test_mals_inference_helpers_for_loose_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'LooseMod'
            flow_dir = root / 'Event' / 'EventFlow'
            mals_dir = root / 'Mals'
            flow_dir.mkdir(parents=True)
            mals_dir.mkdir(parents=True)
            flow_path = flow_dir / 'Demo.bfevfl.zs'
            mals_path = mals_dir / 'USen.Product.110.sarc.zs'
            flow_path.write_bytes(b'')
            mals_path.write_bytes(b'')

            self.assertEqual(infer_eventflow_owner_root(str(flow_path)), root)
            self.assertEqual(infer_eventflow_mals_dir(str(flow_path)), mals_dir)
            self.assertEqual(infer_mals_archive_for_flow_path(str(flow_path)), str(mals_path))

    def test_mals_current_display_uses_vanilla_romfs(self):
        old_romfs_path = totk_zs.get_romfs_path()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                romfs = Path(tmp) / 'romfs'
                mals_dir = romfs / 'Mals'
                mals_dir.mkdir(parents=True)
                mals_path = mals_dir / 'USen.Product.110.sarc.zs'
                mals_path.write_bytes(b'')
                totk_zs.set_romfs_path(str(romfs))

                self.assertEqual(
                    current_mals_display_name(MALS_MODE_INFERRED, str(mals_path), '', ''),
                    'Vanilla',
                )
        finally:
            totk_zs.set_romfs_path(str(old_romfs_path) if old_romfs_path else None)

    def test_mals_current_display_uses_manual_label_for_manual_mode(self):
        self.assertEqual(
            current_mals_display_name(
                MALS_MODE_MANUAL,
                r'C:\Mods\Example\romfs\Mals\USen.Product.110.sarc.zs',
                '',
                r'C:\Mods\Example\romfs\Mals\USen.Product.110.sarc.zs',
            ),
            'Manual',
        )

    def test_available_mals_locales_include_known_totk_locales(self):
        locales = available_mals_locale_names('', '')
        for locale in ['CNzh', 'EUfr', 'JPja', 'KRko', 'USen', 'USfr']:
            self.assertIn(locale, locales)

    def test_find_eventflow_file_in_directory_prefers_totk_suffix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            preferred = root / 'ExternalFlow.bfevfl.zs'
            fallback = root / 'ExternalFlow.evfl.zs'
            preferred.write_bytes(b'')
            fallback.write_bytes(b'')

            self.assertEqual(
                find_eventflow_file_in_directory(root, 'ExternalFlow'),
                str(preferred),
            )
            self.assertEqual(
                find_eventflow_file_in_directory(root, 'ExternalFlow.bfevfl.zs'),
                str(preferred),
            )

    def test_vanilla_romfs_path_helper(self):
        old_romfs_path = totk_zs.get_romfs_path()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                romfs = Path(tmp) / 'romfs'
                flow_path = romfs / 'Event' / 'EventFlow' / 'Demo.bfevfl.zs'
                mod_path = Path(tmp) / 'Mod' / 'Event' / 'EventFlow' / 'Demo.bfevfl.zs'
                flow_path.parent.mkdir(parents=True)
                mod_path.parent.mkdir(parents=True)
                flow_path.write_bytes(b'')
                mod_path.write_bytes(b'')
                totk_zs.set_romfs_path(str(romfs))

                self.assertTrue(is_vanilla_romfs_path(str(flow_path)))
                self.assertFalse(is_vanilla_romfs_path(str(mod_path)))
        finally:
            totk_zs.set_romfs_path(str(old_romfs_path) if old_romfs_path else None)

    def test_container_xml_roundtrip(self):
        payload = {
            'BoolValue': True,
            'IntValue': 7,
            'FloatValue': 1.25,
            'StringValue': 'Message/Event_001',
        }
        self.assertEqual(
            container_xml.loads_container_dict(container_xml.dumps_container_dict(payload)),
            payload,
        )

    def test_choice_label_ints_are_padded_for_display_only(self):
        self.assertEqual(format_container_display_value('ChoiceLabel1', 0), '0000')
        self.assertEqual(format_container_display_value('ChoiceLabel2', 12), '0012')
        self.assertEqual(format_container_display_value('ChoiceLabel3', '7'), '0007')
        self.assertEqual(format_container_display_value('ChoiceNumber', 2), 2)

        container = Container()
        container.data = {
            'ChoiceLabel1': 0,
            'ChoiceNumber': 2,
        }
        model = ContainerModel(None, container)
        choice_index = model.createIndex(0, ContainerModelColumn.Value)
        count_index = model.createIndex(1, ContainerModelColumn.Value)

        self.assertEqual(model.data(choice_index, qc.Qt.DisplayRole), '0000')
        self.assertEqual(model.data(choice_index, qc.Qt.ToolTipRole), '0000')
        self.assertEqual(model.data(choice_index, qc.Qt.EditRole), 0)
        self.assertEqual(model.data(count_index, qc.Qt.DisplayRole), 2)

    def test_event_parameter_summary_pads_choice_labels(self):
        event = Event()
        event.name = 'Event1'
        event.data = ActionEvent()
        event.data.params = Container()
        event.data.params.data = {
            'ChoiceLabel1': 0,
            'ChoiceNumber': 2,
        }

        model = EventModel()
        model.l = [event]
        index = model.createIndex(0, EventModelColumn.Parameters)

        self.assertIn('ChoiceLabel1=0000', model.data(index, qc.Qt.DisplayRole))
        self.assertIn('<b>ChoiceLabel1</b>: 0000', model.data(index, qc.Qt.ToolTipRole))

    def test_event_edit_input_cleanup_helpers(self):
        self.assertEqual(
            _parse_parameter_payload({
                'format': 'TOTKEventEditorParameters',
                'node_type': 'action',
                'params': {'MessageId': 'EventFlowMsg/CC_Test:talk_000'},
            }),
            ({'MessageId': 'EventFlowMsg/CC_Test:talk_000'}, 'action'),
        )
        self.assertEqual(
            _parse_parameter_payload({'EventTalk': {'MessageId': 'EventFlowMsg/CC_Test:talk_000'}}, 'EventTalk'),
            ({'MessageId': 'EventFlowMsg/CC_Test:talk_000'}, None),
        )
        self.assertEqual(
            _parse_parameter_payload({'EventTalk': {'MessageId': 'EventFlowMsg/CC_Test:talk_000'}}),
            ({'MessageId': 'EventFlowMsg/CC_Test:talk_000'}, None),
        )

    def test_node_property_period_findings_are_collected_on_close(self):
        container = Container()
        container.data = {
            'MessageId': 'EventFlowMsg/CC_Test:talk_000.bad',
            'BackupFile': 'EventFlowMsg/Other_Test.msbt',
            'DisplayName': 'Npc.Test',
        }

        findings = _parameter_period_findings(container)

        self.assertEqual(
            findings,
            [
                {'field': 'MessageId', 'parts': {'ID': 'talk_000.bad'}},
                {'field': 'BackupFile', 'value': 'EventFlowMsg/Other_Test.msbt'},
            ],
        )
        self.assertEqual(
            _plain_period_finding('Flowchart', 'CC_Test.bfevfl.zs'),
            {'field': 'Flowchart', 'value': 'CC_Test.bfevfl.zs'},
        )
        self.assertEqual(
            _plain_period_finding('Flowchart', 'CC_Test'),
            None,
        )
        self.assertEqual(
            _parameter_period_findings(Container()),
            [],
        )
        self.assertEqual(
            _format_period_finding({
                'field': 'MessageId',
                'parts': {'ID': 'talk_000.bad'},
            }),
            'Message:\n  ID:   talk_000.bad',
        )
        self.assertEqual(
            _format_period_finding({
                'field': 'MessageId',
                'parts': {'MSBT': 'EventFlowMsg/CC_Test.msbt'},
            }),
            'Message:\n  MSBT: EventFlowMsg/CC_Test.msbt',
        )
        self.assertEqual(
            _format_period_finding({
                'field': 'MessageId',
                'parts': {
                    'MSBT': 'EventFlowMsg/CC_Test.msbt',
                    'ID': 'talk_000.bad',
                },
            }),
            'Message:\n  MSBT: EventFlowMsg/CC_Test.msbt\n  ID:   talk_000.bad',
        )

    def test_actor_xml_roundtrip(self):
        payload = [
            {
                'name': 'Npc_Test',
                'sub_name': '',
                'argument_name': '',
                'argument_entry_point': None,
                'concurrent_clips': 65535,
                'actions': ['Talk'],
                'queries': ['IsOnInstEventFlag'],
                'params': {'MessageId': 'EventFlowMsg/Npc_Test:Talk_001'},
            }
        ]
        self.assertEqual(actor_xml.loads_actors(actor_xml.dumps_actors(payload)), payload)

    def test_entry_point_tree_xml_roundtrip(self):
        payload = {
            'version': 2,
            'events': [
                {
                    'source_idx': 0,
                    'kind': 'sub_flow',
                    'params': None,
                    'entry_point_name': 'Entry0',
                    'res_flowchart_name': '',
                }
            ],
            'actors': [],
            'entry_points': [
                {
                    'name': 'Entry0',
                    'items': {},
                    'main_event_idx': 0,
                    'main_event_name': 'Event0',
                }
            ],
        }
        expected = {
            'version': 2,
            'events': [
                {
                    'source_idx': 0,
                    'kind': 'sub_flow',
                    'entry_point_name': 'Entry0',
                    'res_flowchart_name': '',
                }
            ],
            'actors': [],
            'entry_points': [
                {
                    'name': 'Entry0',
                    'items': {},
                    'main_event_idx': 0,
                    'main_event_name': 'Event0',
                }
            ],
        }
        self.assertEqual(
            entry_point_tree_xml.loads_payload(entry_point_tree_xml.dumps_payload(payload)),
            expected,
        )

    def test_entry_point_copy_tolerates_vanilla_entry_points_without_items(self):
        from eventeditor.flowchart_view import FlowchartView

        flow = EventFlow()
        flow.name = 'InitTalk'
        flow.flowchart = Flowchart()
        flow.flowchart.name = 'InitTalk'

        event = Event()
        event.name = 'Event0'
        event.data = SubFlowEvent()
        event.data.entry_point_name = 'Talk'
        event.data.res_flowchart_name = ''
        flow.flowchart.events = [event]

        entry_point = EntryPoint('InitTalk')
        entry_point.main_event.v = event
        self.assertFalse(hasattr(entry_point, 'items'))
        flow.flowchart.entry_points = [entry_point]

        view = FlowchartView.__new__(FlowchartView)
        view.flow_data = types.SimpleNamespace(flow=flow)

        payload = FlowchartView._serializeEntryPointRowsPayload(view, [0])

        self.assertEqual(payload['entry_points'][0]['name'], 'InitTalk')
        self.assertEqual(payload['entry_points'][0]['items'], {})
        self.assertEqual(payload['events'][0]['kind'], 'sub_flow')

    def test_mals_prefix_matching(self):
        message_ids = {
            'EventFlowMsg/Npc_Test:Talk_001',
            'EventFlowMsg/Npc_Test:Talk_002',
            'EventFlowMsg/Another_Test:Talk_001',
            'MalformedMessageId',
        }
        grouped = mals._group_message_ids_by_prefix(message_ids)
        self.assertEqual(grouped['EventFlowMsg/Npc_Test'], {'Talk_001', 'Talk_002'})
        self.assertEqual(grouped['EventFlowMsg/Another_Test'], {'Talk_001'})
        self.assertEqual(
            mals._matching_prefixes(
                'EventFlowMsg/Npc_Test.msbt',
                ['EventFlowMsg/Npc_Test', 'Npc_Test', 'Missing'],
            ),
            ['EventFlowMsg/Npc_Test', 'Npc_Test'],
        )

    def test_mals_lbl1_empty_terminal_group(self):
        label = b'talk_000_help01'
        group_count = 2
        table_end = 4 + group_count * 8
        section = bytearray()
        section += struct.pack('<I', group_count)
        section += struct.pack('<II', 1, table_end)
        section += struct.pack('<II', 0, table_end + 1 + len(label) + 4)
        section += bytes([len(label)])
        section += label
        section += struct.pack('<I', 41)

        self.assertEqual(
            mals._parse_lbl1(bytes(section), '<'),
            {41: 'talk_000_help01'},
        )

    def test_mals_missing_archive_message_includes_locale(self):
        self.assertEqual(mals.mals_file_not_found_text('EUfr'), '<EUfr Mals file not found>')
        self.assertEqual(mals.mals_file_not_found_text(''), '<Selected Mals file not found>')

    def test_packaged_assets_resolve(self):
        for asset in [
            'assets/main.js',
            'assets/main.css',
            'assets/index.html',
            'assets/material_visibility_24.svg',
            'assets/material_visibility_off_24.svg',
        ]:
            self.assertTrue(Path(util.get_path(asset)).is_file(), asset)

    def test_graph_ui_labels_and_hooks(self):
        source_root = Path(__file__).resolve().parents[1] / 'eventeditor'
        main_js = Path(util.get_path('assets/main.js')).read_text(encoding='utf-8')
        main_py = (source_root / '__main__.py').read_text(encoding='utf-8')
        flowchart_py = (source_root / 'flowchart_view.py').read_text(encoding='utf-8')

        self.assertIn("('Text', 'mals')", flowchart_py)
        self.assertNotIn('Mals text', flowchart_py)
        self.assertIn("QAction('Open Mals'", main_py)
        self.assertNotIn('Open Current Mals', main_py)
        self.assertIn("self.mals_locale_menu = q.QMenu(f'Locale: {DEFAULT_MALS_LOCALE}'", main_py)
        self.assertIn("def setMalsLocale", main_py)
        self.assertIn("settings.setValue('locale', self._mals_locale)", main_py)
        self.assertIn("No {self._mals_locale} Mals archive could be found", main_py)
        self.assertIn("mals.mals_file_not_found_text(self._mals_locale)", main_py)
        self.assertIn("totk_rom_root = settings.value('paths/totk_rom_root')", main_py)
        self.assertIn("ai.set_rom_path(totk_rom_root)", main_py)
        self.assertIn("ai.set_rom_path(str(romfs_root))", main_py)
        self.assertNotIn("ai.set_rom_path(settings.value('paths/rom_root'))", main_py)
        self.assertNotIn("QAction('Show &tags'", main_py)
        self.assertNotIn("'Include text tags'", main_py)
        self.assertNotIn("include_text_tags", main_py)
        self.assertNotIn("'Render MSBT tags as styling'", main_py)
        self.assertIn("'Turn style tags into formatting'", main_py)
        self.assertNotIn("'Show non-text tags'", main_py)
        self.assertIn("'Hide non-formatting tags'", main_py)
        self.assertIn("hide_non_formatting_tags", main_py)
        self.assertNotIn("'Include blank lines'", main_py)
        self.assertIn("'Hide blank lines'", main_py)
        self.assertIn("hide_blank_lines", main_py)
        self.assertIn("'Show text bubble breaks'", main_py)
        self.assertIn("show_text_bubble_breaks", main_py)
        self.assertIn("widget.goToSubflowEntryPoint(idx)", main_js)
        self.assertIn("^ChoiceLabel\\d+$", main_js)
        self.assertIn("formatNodeParamValue(value, key)", main_js)
        self.assertIn(".padStart(4, '0')", main_js)
        self.assertIn("'0': '#ff6634'", main_js)
        self.assertIn("const currentStyle = {};", main_js)
        self.assertIn("hasSvgTextStyle(currentStyle)", main_js)
        self.assertIn(".split('\\n')", main_js)
        self.assertIn("const WRAP_TOKEN_REGEX", main_js)
        self.assertIn("const MESSAGE_BLANK_LINE = '\\u00A0'", main_js)
        self.assertIn("const MESSAGE_BUBBLE_BREAK_LINE = '\\u2063'", main_js)
        self.assertIn("wrappedLines.push(MESSAGE_BLANK_LINE)", main_js)
        self.assertIn("isMessagePageBreakTagToken(token)", main_js)
        self.assertIn("function applyTextBubbleBreaks", main_js)
        self.assertNotIn("bubbleLineCount", main_js)
        self.assertIn("const MESSAGE_BUBBLE_SOURCE_LINE_LIMIT = 3", main_js)
        self.assertIn("let sourceTextLineCount = 0", main_js)
        self.assertIn("if (showMessageBubbleBreaks && !inBlankLineGroup && sourceTextLineCount > 0)", main_js)
        self.assertIn("pushMessageBubbleBreak(lines)", main_js)
        self.assertIn("function appendMessageIdBlock", main_js)
        self.assertIn("appendWrappedLabelLineWithIndent(nextLabel, '  MSBT: '", main_js)
        self.assertIn("appendWrappedLabelLineWithIndent(nextLabel, '  ID:   '", main_js)
        self.assertIn("key === 'MessageId'", main_js)
        self.assertIn("function getNodeLayoutLabel", main_js)
        self.assertIn("label: getNodeLayoutLabel(rawLabel)", main_js)
        self.assertIn("rawLabel,", main_js)
        self.assertIn("this._restoreRawNodeLabels(visibleGraph)", main_js)
        self.assertIn("this._fitNodeBoxesToLabels()", main_js)
        self.assertIn("shape.setAttribute('width'", main_js)
        self.assertIn("const nextWidth = Math.max(currentWidth, fittedWidth)", main_js)
        self.assertIn("const nextHeight = Math.max(currentHeight, fittedHeight)", main_js)
        self.assertIn("centerY - (nextHeight / 2)", main_js)
        self.assertIn("const GRAPH_FIT_PADDING = 40", main_js)
        self.assertIn("const GRAPH_FIT_MAX_SCALE = 1", main_js)
        self.assertIn("const READABLE_NODE_SCALE = 1", main_js)
        self.assertIn("fitToContent(padding=GRAPH_FIT_PADDING)", main_js)
        self.assertIn("availableWidth / bbox.width", main_js)
        self.assertIn("let resetViewportOnNextLoad = true", main_js)
        self.assertIn("graph.renderer.fitToContent()", main_js)
        self.assertIn("graph.renderer.scrollTo(id, true, 500, READABLE_NODE_SCALE)", main_js)
        self.assertIn("graph.renderer.scrollTo(id, true, 0, READABLE_NODE_SCALE)", main_js)
        self.assertNotIn("graph.renderer.setTranslate([20, 20])", main_js)
        self.assertNotIn("const render = dagreD3.render()", main_js)
        self.assertIn("const dagreRenderer = dagreD3.render()", main_js)
        self.assertIn("closestNodeIdToViewportCenter", main_js)
        self.assertIn("preservedFocusPoint = preservedFocusNodeId == null ? null : graph.renderer.viewportCenterPoint()", main_js)
        self.assertIn(r"\{\{[^{}\n]+\}\}|[ \t]+|[^\s{}]+", main_js)
        self.assertIn("messageTokenVisibleText(token)", main_js)
        self.assertIn("let showNonTextMessageTags = true", main_js)
        self.assertIn("let includeMessageBlankLines = true", main_js)
        self.assertIn("let showMessageBubbleBreaks = true", main_js)
        self.assertIn("lines.push(MESSAGE_BLANK_LINE)", main_js)
        self.assertIn("sourceTextLineCount >= MESSAGE_BUBBLE_SOURCE_LINE_LIMIT", main_js)
        self.assertIn("window.eventEditorSetShowNonTextMessageTags", main_js)
        self.assertIn("window.eventEditorSetIncludeMessageBlankLines", main_js)
        self.assertIn("window.eventEditorSetShowMessageBubbleBreaks", main_js)
        self.assertIn("!showNonTextMessageTags && !isMessageFormatTag(tag)", main_js)
        self.assertIn("setNonTextMessageTagsVisible", flowchart_py)
        self.assertIn("onHideNonFormattingMalsTagsChanged", main_py)
        self.assertIn("eventTagVisibilityChanged.emit(self._include_mals_text_tags)", main_py)
        self.assertIn("setMessageBlankLinesIncluded", flowchart_py)
        self.assertIn("onHideMalsBlankLinesChanged", main_py)
        self.assertIn("setMessageBubbleBreaksShown", flowchart_py)
        self.assertIn("menu.addAction('Edit', lambda checked=False: self.doubleClicked.emit())", flowchart_py)
        self.assertIn("menu.addAction('Show only selected', self.showOnlySelectedEntryPoints)", flowchart_py)
        self.assertIn("menu.addAction('Show All', lambda checked=False: self.webShowAllEvents())", flowchart_py)
        self.assertIn("def showOnlySelectedEntryPoints", flowchart_py)
        self.assertIn("self.flow_data.entry_point_model.isHiddenRow(source_row)", flowchart_py)
        self.assertIn("self.flow_data.entry_point_model.setRowsHidden([source_row], False)", flowchart_py)
        self.assertIn('def _copyEntryPointItems(self, entry_point: EntryPoint)', flowchart_py)
        self.assertIn("getattr(entry_point, 'items', {})", flowchart_py)
        self.assertIn('def _setEntryPointItems(self, entry_point: EntryPoint, items:', flowchart_py)
        self.assertIn("self._setEntryPointItems(entry_point, entry_payload.get('items', {}))", flowchart_py)
        self.assertIn("q.QMessageBox.critical(self, 'Copy entry points'", flowchart_py)
        self.assertIn("self.web_object.preserveViewportRequested.emit()", flowchart_py)
        self.assertIn("self._launchNewInstanceForPath(path, entry_point_name=entry_point_name)", main_py)
        self.assertIn("parser.add_argument('--entry-point'", main_py)
        self.assertIn("self.selectStartupEntryPointIfRequested()", main_py)

    def test_windows_build_names_release_executable_with_version(self):
        workflow = (Path(__file__).resolve().parents[1] / '.github' / 'workflows' / 'build-windows.yml').read_text(encoding='utf-8')
        self.assertIn('$appBundleName = "TOTK Event Editor $releaseVersion"', workflow)
        self.assertIn('--name "$env:APP_BUNDLE_NAME"', workflow)
        self.assertIn('Compress-Archive -Path "dist/$env:APP_BUNDLE_NAME/*"', workflow)

    def test_event_chooser_headers_sort_ascending_then_descending(self):
        source_root = Path(__file__).resolve().parents[1] / 'eventeditor'
        event_view_py = (source_root / 'event_view.py').read_text(encoding='utf-8')
        event_chooser_py = (source_root / 'event_chooser_dialog.py').read_text(encoding='utf-8')
        actor_view_py = (source_root / 'actor_view.py').read_text(encoding='utf-8')
        container_view_py = (source_root / 'container_view.py').read_text(encoding='utf-8')
        container_model_py = (source_root / 'container_model.py').read_text(encoding='utf-8')
        event_branch_editors_py = (source_root / 'event_branch_editors.py').read_text(encoding='utf-8')
        event_edit_dialog_py = (source_root / 'event_edit_dialog.py').read_text(encoding='utf-8')
        sortable_proxy_model_py = (source_root / 'sortable_proxy_model.py').read_text(encoding='utf-8')
        ai_py = (source_root / 'ai.py').read_text(encoding='utf-8')

        self.assertIn('class SortableHeaderProxyModel(qc.QSortFilterProxyModel):', sortable_proxy_model_py)
        self.assertIn("return f'{value} ({self._sort_descriptor_text})'", sortable_proxy_model_py)
        self.assertIn('enable_sorting: bool=True', event_view_py)
        self.assertIn('enable_sorting=True', event_chooser_py)
        self.assertIn('self.event_proxy_model = SortableHeaderProxyModel(self)', event_view_py)
        self.assertIn('self.event_proxy_model.setSortCaseSensitivity(qc.Qt.CaseInsensitive)', event_view_py)
        self.assertIn('self.event_view.horizontalHeader().sectionClicked.connect(self.onHeaderClicked)', event_view_py)
        self.assertIn('if self._sort_column == section and self._sort_order == qc.Qt.AscendingOrder:', event_view_py)
        self.assertIn('self._sort_order = qc.Qt.DescendingOrder', event_view_py)
        self.assertIn('self._sort_order = qc.Qt.AscendingOrder', event_view_py)
        self.assertIn("self.event_proxy_model.setSortDescriptor(section, 'Z-A' if self._sort_order == qc.Qt.DescendingOrder else 'A-Z')", event_view_py)
        self.assertIn('self.event_proxy_model.sort(section, self._sort_order)', event_view_py)
        self.assertIn('self.actor_proxy_model = SortableHeaderProxyModel(self)', actor_view_py)
        self.assertIn('self.actor_view.horizontalHeader().sectionClicked.connect(self.onActorHeaderClicked)', actor_view_py)
        self.assertIn('if self.actor_sort_column == section and self.actor_sort_order == qc.Qt.AscendingOrder:', actor_view_py)
        self.assertIn("self.actor_proxy_model.setSortDescriptor(section, 'Z-A' if self.actor_sort_order == qc.Qt.DescendingOrder else 'A-Z')", actor_view_py)
        self.assertIn('self.actor_proxy_model.sort(section, self.actor_sort_order)', actor_view_py)
        self.assertIn('self._mapActorIndexToSource(idx)', actor_view_py)
        self.assertIn('self.proxy_model = SortableHeaderProxyModel(self)', container_view_py)
        self.assertIn('hheader.sectionClicked.connect(self.onHeaderClicked)', container_view_py)
        self.assertIn("descriptor = 'A-Z'", container_view_py)
        self.assertIn("descriptor = 'Z-A'", container_view_py)
        self.assertIn('elif section == ContainerModelColumn.Key:', container_view_py)
        self.assertIn("descriptor = 'File'", container_view_py)
        self.assertIn('self.proxy_model.setSortDescriptor(section, descriptor)', container_view_py)
        self.assertIn('self.proxy_model.sort(sort_column, self.sort_order)', container_view_py)
        self.assertIn('idx = self._mapIndexToSource(smodel.selectedIndexes()[0])', container_view_py)
        self.assertIn('show_json_tools=False', container_view_py)
        self.assertIn('if show_json_tools:', container_view_py)
        self.assertNotIn('autofillRequested', container_view_py)
        self.assertNotIn('reorderRequested', container_view_py)
        self.assertNotIn("QPushButton('Auto fill')", container_view_py)
        self.assertNotIn("QPushButton('Reorder')", container_view_py)
        self.assertNotIn('def prompt_file_suffix_action', container_model_py)
        self.assertNotIn('Cancel keeps editing.', container_model_py)
        self.assertNotIn('editCancelled', container_model_py)
        self.assertNotIn('_file_suffix_prompt_active', container_model_py)
        self.assertNotIn('def strip_message_id_file_suffix(value: str)', container_model_py)
        self.assertNotIn('def strip_file_suffix(value: str)', container_model_py)
        self.assertNotIn('ContainerItemDelegate', container_view_py)
        self.assertIn('util.set_view_delegate(self.tview)', container_view_py)
        self.assertIn('def sort(self, column: int, order: qc.Qt.SortOrder = qc.Qt.AscendingOrder) -> None:', event_branch_editors_py)
        self.assertIn("return f'{text} ({self._sort_descriptor_text})'", event_branch_editors_py)
        self.assertIn('self.tview.horizontalHeader().sectionClicked.connect(self.onHeaderClicked)', event_branch_editors_py)
        self.assertIn("self.model.setSortDescriptor(section, 'Z-A' if self.sort_order == qc.Qt.DescendingOrder else 'A-Z')", event_branch_editors_py)
        self.assertIn('self.model.sort(section, self.sort_order)', event_branch_editors_py)
        self.assertIn('show_json_tools=True', event_edit_dialog_py)
        self.assertIn('self.param_view.copyJsonRequested.connect(self.onCopyJsonRequested)', event_edit_dialog_py)
        self.assertIn('self.param_view.pasteJsonRequested.connect(self.onPasteJsonRequested)', event_edit_dialog_py)
        self.assertIn("self.flowchart_ledit.setPlaceholderText(f'{self.flow_data.flow.name} (edit to specify an external flowchart)')", event_edit_dialog_py)
        self.assertNotIn('self.flowchart_ledit.editingFinished.connect(self.normalizeFlowchartName)', event_edit_dialog_py)
        self.assertNotIn('def normalizeFlowchartName(self)', event_edit_dialog_py)
        self.assertIn('def prompt_node_property_period_warning', event_edit_dialog_py)
        self.assertIn('One or more paths to external files contains a period.', event_edit_dialog_py)
        self.assertIn('Note that file extensions, like .msbt or .evfl, are not required.', event_edit_dialog_py)
        self.assertIn("details = q.QLabel('\\n\\n'.join(_format_period_finding(finding) for finding in findings))", event_edit_dialog_py)
        self.assertIn('details.setTextFormat(qc.Qt.PlainText)', event_edit_dialog_py)
        self.assertIn('details.setTextInteractionFlags(qc.Qt.TextSelectableByMouse)', event_edit_dialog_py)
        self.assertNotIn('QPlainTextEdit', event_edit_dialog_py)
        self.assertNotIn('FixedFont', event_edit_dialog_py)
        self.assertIn("q.QPushButton('Go back')", event_edit_dialog_py)
        self.assertIn("q.QPushButton('Ignore')", event_edit_dialog_py)
        self.assertIn('def handlePeriodsBeforeClose(self) -> str:', event_edit_dialog_py)
        self.assertIn('self.handlePeriodsBeforeClose()', event_edit_dialog_py)
        self.assertNotIn("q.QPushButton('Keep As-Is'", event_edit_dialog_py)
        self.assertNotIn("q.QPushButton('Close Anyway')", event_edit_dialog_py)
        self.assertNotIn("q.QPushButton('Remove File Suffixes')", event_edit_dialog_py)
        self.assertNotIn('def applyFileSuffixRemovals', event_edit_dialog_py)
        self.assertNotIn('Proposed:', event_edit_dialog_py)
        self.assertIn('PARAMETER_CLIPBOARD_MIME_TYPE', event_edit_dialog_py)
        self.assertIn('def set_parameter_clipboard', event_edit_dialog_py)
        self.assertIn('def get_parameter_clipboard', event_edit_dialog_py)
        self.assertIn('def confirm_parameter_paste_node_type', event_edit_dialog_py)
        self.assertIn('q.QMessageBox.Ok | q.QMessageBox.Cancel', event_edit_dialog_py)
        self.assertIn('This is rarely intentional. Continue?', event_edit_dialog_py)
        self.assertIn('def parameterClipboardNodeType(self)', event_edit_dialog_py)
        self.assertIn('confirm_parameter_paste_node_type(self, source_node_type, self.parameterClipboardNodeType())', event_edit_dialog_py)
        self.assertIn("confirm_parameter_paste_node_type(self, source_node_type, 'subflow')", event_edit_dialog_py)
        self.assertNotIn('Flowchart name (optional)', event_edit_dialog_py)
        self.assertNotIn('Note: this flowchart', event_edit_dialog_py)
        self.assertNotIn('<self> (edit to specify an external flowchart)', event_edit_dialog_py)
        self.assertNotIn('has_autofill_btn=True', event_edit_dialog_py)
        self.assertNotIn('onAutofillRequested', event_edit_dialog_py)
        self.assertNotIn('onReorderRequested', event_edit_dialog_py)
        self.assertNotIn('autofillRequested', event_edit_dialog_py)
        self.assertNotIn('reorderRequested', event_edit_dialog_py)
        self.assertNotIn('COMMON_EVENT_PARAMETER_ORDER', event_edit_dialog_py)
        self.assertIn('def clear_cached_metadata() -> None:', ai_py)
        self.assertIn('load_aiprog.cache_clear()', ai_py)
        self.assertIn('ai_def_instance.clear()', ai_py)
        self.assertIn('def clear(self) -> None:', ai_py)

    def test_plain_and_gzip_flow_roundtrip(self):
        flow = EventFlow()
        flow.name = 'SmokeFlow'
        flow.flowchart = Flowchart()
        flow.flowchart.name = 'SmokeFlow'

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            for suffix in ['.bfevfl', '.bfevfl.gz']:
                path = tmp_dir / f'SmokeFlow{suffix}'
                util.write_flow(str(path), flow)
                loaded = EventFlow()
                util.read_flow(str(path), loaded)
                self.assertEqual(loaded.name, 'SmokeFlow')


if __name__ == '__main__':
    unittest.main()
