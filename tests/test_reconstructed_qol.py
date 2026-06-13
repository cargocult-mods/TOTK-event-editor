import tempfile
import types
import unittest
import os
from pathlib import Path
import struct

from evfl import Actor, Container, Event, EventFlow, Flowchart
from evfl.common import RequiredIndex, StringHolder
from evfl.entry_point import EntryPoint
from evfl.event import ActionEvent, SubFlowEvent, SwitchEvent
import oead
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
    build_latest_release_request,
    build_update_info,
    extract_update_summary,
    GITHUB_LATEST_RELEASE_API_URL,
    GITHUB_REPOSITORY_SLUG,
    GITHUB_REPOSITORY_URL,
    GITHUB_RELEASES_URL,
    is_newer_release_version,
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
    parse_release_version,
    UPDATE_SUMMARY_END,
    UPDATE_SUMMARY_START,
)
import eventeditor.actor_xml as actor_xml
import eventeditor.container_xml as container_xml
import eventeditor.entry_point_tree_xml as entry_point_tree_xml
import eventeditor.event_library as event_library
import eventeditor._version as versioneer_runtime_config
import eventeditor.mals as mals
import eventeditor.totk_zs as totk_zs
import eventeditor.util as util


def make_action_flow(flow_name, actor_name, action_name, params):
    flow = EventFlow()
    flow.name = flow_name
    flow.flowchart = Flowchart()
    flow.flowchart.name = flow_name

    actor = Actor()
    actor.identifier.name = actor_name
    actor.actions = [StringHolder(action_name)]

    event = Event()
    event.name = 'Event0'
    event.data = ActionEvent()
    event.data.actor.v = actor
    event.data.actor_action.v = actor.actions[0]
    event.data.params = Container()
    event.data.params.data = dict(params)

    flow.flowchart.actors = [actor]
    flow.flowchart.events = [event]
    flow.flowchart.entry_points = []
    return flow


def make_query_flow(flow_name, actor_name, query_name, params):
    flow = EventFlow()
    flow.name = flow_name
    flow.flowchart = Flowchart()
    flow.flowchart.name = flow_name

    actor = Actor()
    actor.identifier.name = actor_name
    actor.queries = [StringHolder(query_name)]

    query_event = Event()
    query_event.name = 'EventQuery'
    query_event.data = SwitchEvent()
    query_event.data.actor.v = actor
    query_event.data.actor_query.v = actor.queries[0]
    query_event.data.params = Container()
    query_event.data.params.data = dict(params)

    target_event = Event()
    target_event.name = 'EquippedBranch'
    target_ref = RequiredIndex()
    target_ref.v = target_event
    query_event.data.cases[0] = target_ref

    flow.flowchart.actors = [actor]
    flow.flowchart.events = [query_event, target_event]
    flow.flowchart.entry_points = []
    return flow


def write_sarc(path, files):
    writer = oead.SarcWriter()
    for name, data in files.items():
        writer.files[name] = data
    _alignment, sarc_data = writer.write()
    path.parent.mkdir(parents=True)
    path.write_bytes(bytes(sarc_data))


class ReconstructedQoLTests(unittest.TestCase):
    def test_public_identity_strings(self):
        self.assertEqual(APP_DISPLAY_NAME, 'TOTK EventEditor')
        self.assertEqual(GITHUB_REPOSITORY_SLUG, 'cargocult-mods/TOTK-event-editor')
        self.assertEqual(GITHUB_REPOSITORY_URL, 'https://github.com/cargocult-mods/TOTK-event-editor')
        self.assertEqual(GITHUB_RELEASES_URL, 'https://github.com/cargocult-mods/TOTK-event-editor/releases')
        self.assertEqual(GITHUB_LATEST_RELEASE_API_URL, 'https://api.github.com/repos/cargocult-mods/TOTK-event-editor/releases/latest')
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

    def test_update_check_helpers(self):
        self.assertEqual(parse_release_version('v1.2.3'), (1, 2, 3))
        self.assertEqual(parse_release_version('v1.2.3.post1.dev2'), (1, 2, 3))
        self.assertIsNone(parse_release_version('development build'))
        self.assertTrue(is_newer_release_version('v1.2.1', 'v1.2.0'))
        self.assertTrue(is_newer_release_version('v1.10.0', 'v1.2.9'))
        self.assertFalse(is_newer_release_version('v1.2.0', 'v1.2.0'))
        self.assertFalse(is_newer_release_version('v1.2.0', 'development build'))

        marked_body = (
            'Long release notes\n'
            f'{UPDATE_SUMMARY_START}\n'
            '- Short item one\n'
            '- Short item two\n'
            f'{UPDATE_SUMMARY_END}\n'
            '- Long item'
        )
        self.assertEqual(extract_update_summary(marked_body), '- Short item one\n- Short item two')

        fallback_body = "Written by Codex:\n\nWhat's new:\n- One\n- Two\n- Three\n- Four\n- Five\n- Six\n"
        self.assertEqual(extract_update_summary(fallback_body), "What's new:\n- One\n- Two\n- Three\n- Four\n- Five")

        update_info = build_update_info('v1.2.0', {
            'tag_name': 'v1.2.1',
            'html_url': 'https://example.invalid/release',
            'body': marked_body,
        })
        self.assertEqual(update_info['version'], 'v1.2.1')
        self.assertEqual(update_info['url'], 'https://example.invalid/release')
        self.assertIn('Short item one', update_info['summary'])

        request = build_latest_release_request('http://127.0.0.1:9/releases/latest')
        self.assertEqual(request.full_url, 'http://127.0.0.1:9/releases/latest')
        self.assertEqual(request.get_header('Accept'), 'application/vnd.github+json')

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

    def test_event_library_scans_mod_then_vanilla_eventflows(self):
        event_library.clear_event_library_cache()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            previous_cache_dir = os.environ.get(event_library._VANILLA_EVENT_LIBRARY_CACHE_ENV)
            def restore_cache_dir():
                if previous_cache_dir is None:
                    os.environ.pop(event_library._VANILLA_EVENT_LIBRARY_CACHE_ENV, None)
                else:
                    os.environ[event_library._VANILLA_EVENT_LIBRARY_CACHE_ENV] = previous_cache_dir
                event_library.clear_event_library_cache()
            self.addCleanup(restore_cache_dir)
            os.environ[event_library._VANILLA_EVENT_LIBRARY_CACHE_ENV] = str(root / 'EventLibraryCache')
            event_library.clear_event_library_cache(clear_disk=True)

            mod_flow_dir = root / 'Mod' / 'romfs' / 'Event' / 'EventFlow'
            other_mod_flow_dir = root / 'OtherMod' / 'romfs' / 'Event' / 'EventFlow'
            vanilla_flow_dir = root / 'Vanilla' / 'Event' / 'EventFlow'
            mod_flow_dir.mkdir(parents=True)
            other_mod_flow_dir.mkdir(parents=True)
            vanilla_flow_dir.mkdir(parents=True)
            mod_path = mod_flow_dir / 'Current.bfevfl'
            other_mod_path = other_mod_flow_dir / 'Current.bfevfl'
            vanilla_path = vanilla_flow_dir / 'Vanilla.bfevfl'
            util.write_flow(str(mod_path), make_action_flow('Current', 'Player', 'EventTriggerModOnly', {'Slot': 1}))
            util.write_flow(str(other_mod_path), make_action_flow('Current', 'Player', 'EventTriggerOtherMod', {'Slot': 4}))
            util.write_flow(str(vanilla_path), make_action_flow('Vanilla', 'Player', 'EventTriggerVanillaOnly', {'EquipmentState': 2}))
            (mod_flow_dir / 'Broken.bfevfl').write_bytes(b'not an eventflow')

            result = event_library.build_actor_event_library(
                'Player',
                event_library.EVENT_LIBRARY_ACTION,
                flow_path=str(mod_path),
                vanilla_romfs=root / 'Vanilla',
            )

            names = [entry.name for entry in result.entries]
            self.assertIn('EventTriggerModOnly', names)
            self.assertIn('EventTriggerVanillaOnly', names)
            self.assertLess(names.index('EventTriggerModOnly'), names.index('EventTriggerVanillaOnly'))
            mod_entry = next(entry for entry in result.entries if entry.name == 'EventTriggerModOnly')
            self.assertIn('Mod flow examples', mod_entry.sources)
            self.assertEqual(mod_entry.default_params(), {'Slot': 1})
            self.assertEqual(mod_entry.vanilla_parameter_names(), [])
            vanilla_entry = next(entry for entry in result.entries if entry.name == 'EventTriggerVanillaOnly')
            self.assertEqual(vanilla_entry.vanilla_parameter_names(), ['EquipmentState'])
            self.assertEqual(
                vanilla_entry.vanilla_parameters()[0].seed_value_for_sources(lambda source: source.startswith('Vanilla ')),
                2,
            )
            self.assertFalse(result.from_cache)
            self.assertTrue(any((root / 'EventLibraryCache').glob('vanilla-v*.pickle')))
            self.assertTrue(any(
                error.startswith('Broken.bfevfl - Could not parse or decompress EventFlow:')
                for error in result.errors
            ))

            cached = event_library.build_actor_event_library(
                'Player',
                event_library.EVENT_LIBRARY_ACTION,
                flow_path=str(mod_path),
                vanilla_romfs=root / 'Vanilla',
                current_revision=1,
            )
            self.assertTrue(cached.from_cache)
            revision_changed = event_library.build_actor_event_library(
                'Player',
                event_library.EVENT_LIBRARY_ACTION,
                flow_path=str(mod_path),
                vanilla_romfs=root / 'Vanilla',
                current_revision=99,
            )
            self.assertTrue(revision_changed.from_cache)

            util.write_flow(
                str(vanilla_path),
                make_action_flow('Vanilla', 'Player', 'EventTriggerVanillaChanged', {'EquipmentState': 9}),
            )
            event_library.clear_event_library_cache()
            cross_mod = event_library.build_actor_event_library(
                'Player',
                event_library.EVENT_LIBRARY_ACTION,
                flow_path=str(other_mod_path),
                vanilla_romfs=root / 'Vanilla',
            )
            cross_mod_names = [entry.name for entry in cross_mod.entries]
            self.assertIn('EventTriggerVanillaOnly', cross_mod_names)
            self.assertNotIn('EventTriggerVanillaChanged', cross_mod_names)

            forced = event_library.build_actor_event_library(
                'Player',
                event_library.EVENT_LIBRARY_ACTION,
                flow_path=str(other_mod_path),
                vanilla_romfs=root / 'Vanilla',
                force_rebuild=True,
            )
            forced_names = [entry.name for entry in forced.entries]
            self.assertIn('EventTriggerVanillaChanged', forced_names)
            self.assertNotIn('EventTriggerVanillaOnly', forced_names)

            vanilla_current_flow = make_action_flow(
                'CurrentVanilla',
                'Player',
                'EventTriggerVanillaCurrent',
                {'EquipmentState': 5},
            )
            vanilla_current_path = vanilla_flow_dir / 'CurrentVanilla.bfevfl'
            util.write_flow(str(vanilla_current_path), vanilla_current_flow)
            vanilla_context = event_library.build_actor_event_library(
                'Player',
                event_library.EVENT_LIBRARY_ACTION,
                current_flow=vanilla_current_flow,
                flow_path=str(vanilla_current_path),
                vanilla_romfs=root / 'Vanilla',
                force_rebuild=True,
            )
            self.assertFalse(vanilla_context.mod_context_enabled)
            self.assertFalse(any(entry.has_mod_source() for entry in vanilla_context.entries))
            vanilla_current_entry = next(
                entry for entry in vanilla_context.entries
                if entry.name == 'EventTriggerVanillaCurrent'
            )
            self.assertIn('Current file', vanilla_current_entry.sources)
            self.assertIn('Vanilla flow examples', vanilla_current_entry.sources)

            util.write_flow(
                str(mod_flow_dir / 'New.bfevfl'),
                make_action_flow('New', 'Player', 'EventTriggerNewInfo', {'Slot': 2}),
            )
            refreshed = event_library.build_actor_event_library(
                'Player',
                event_library.EVENT_LIBRARY_ACTION,
                flow_path=str(mod_path),
                vanilla_romfs=root / 'Vanilla',
            )
            self.assertFalse(refreshed.from_cache)
            self.assertIn('EventTriggerNewInfo', [entry.name for entry in refreshed.entries])

    def test_event_library_records_query_parameters_and_cases(self):
        event_library.clear_event_library_cache()
        flow = make_query_flow('Current', 'Player', 'EventQueryCheckIsEquippedDynamicEquipment', {'DynamicEquipmentSlot': 0})

        result = event_library.build_actor_event_library(
            'Player',
            event_library.EVENT_LIBRARY_QUERY,
            current_flow=flow,
            flow_path='Current.bfevfl',
        )

        self.assertEqual(len(result.entries), 1)
        entry = result.entries[0]
        self.assertEqual(entry.name, 'EventQueryCheckIsEquippedDynamicEquipment')
        self.assertEqual(entry.default_params(), {'DynamicEquipmentSlot': 0})
        self.assertEqual(entry.case_targets, {0: ['EquippedBranch']})
        self.assertEqual(entry.case_count(), 1)
        self.assertEqual(entry.case_value_summary(), '0')
        case_entry = event_library.EventLibraryEntry(event_library.EVENT_LIBRARY_QUERY, 'EventQueryRanges', 0)
        case_entry.case_targets = {value: [] for value in list(range(14)) + [15]}
        self.assertEqual(case_entry.case_value_summary(), '0-13, 15')
        empty_param_vanilla_entry = event_library.EventLibraryEntry(
            event_library.EVENT_LIBRARY_QUERY,
            'EventQueryEquipWeaponSlotType',
            4,
        )
        empty_param_vanilla_entry.add_observed(
            'Vanilla flow examples',
            4,
            'Vanilla.bfevfl',
            'Event0',
            {},
            {0: 'Event0', 1: 'Event1', 2: 'Event2', 3: 'Event3'},
        )
        self.assertTrue(empty_param_vanilla_entry.has_vanilla_baseline())
        self.assertEqual(empty_param_vanilla_entry.vanilla_parameters(), [])
        self.assertEqual(empty_param_vanilla_entry.case_value_summary(), '0-3')
        sample_entry = event_library.EventLibraryEntry(event_library.EVENT_LIBRARY_ACTION, 'EventTriggerSampleLimit', 0)
        for index in range(event_library.MAX_ENTRY_EXAMPLES + 2):
            sample_entry.add_observed('Vanilla flow examples', 4, 'Sample.bfevfl', 'Event{}'.format(index), {'Index': index})
        self.assertEqual(sample_entry.observed_example_count(), event_library.MAX_ENTRY_EXAMPLES + 2)
        self.assertEqual(sample_entry.example_count_label(), str(event_library.MAX_ENTRY_EXAMPLES + 2))
        self.assertEqual(len(sample_entry.examples), event_library.MAX_ENTRY_EXAMPLES)
        self.assertEqual(len(sample_entry.all_observed_examples()), event_library.MAX_ENTRY_EXAMPLES + 2)
        self.assertEqual(len(sample_entry.preview_examples()), event_library.MAX_ENTRY_EXAMPLES)

        mixed_entry = event_library.EventLibraryEntry(event_library.EVENT_LIBRARY_ACTION, 'EventTriggerMixedSources', 0)
        for index in range(4):
            mixed_entry.add_observed('Current file', 0, 'Current.bfevfl', 'EventC{}'.format(index), {'Index': index})
            mixed_entry.add_observed('Mod flow examples', 2, 'Mod.bfevfl', 'EventM{}'.format(index), {'Index': index})
            mixed_entry.add_observed('Vanilla flow examples', 4, 'Vanilla.bfevfl', 'EventV{}'.format(index), {'Index': index})
        preview_groups = [example.source_group() for example in mixed_entry.preview_examples()]
        self.assertEqual(preview_groups.count(event_library.SOURCE_GROUP_CURRENT), 2)
        self.assertEqual(preview_groups.count(event_library.SOURCE_GROUP_MOD), 2)
        self.assertEqual(preview_groups.count(event_library.SOURCE_GROUP_VANILLA), 4)
        self.assertEqual(mixed_entry.preview_examples([]), [])

        unusual_entry = event_library.EventLibraryEntry(event_library.EVENT_LIBRARY_ACTION, 'EventTriggerUsual', 0)
        for index in range(4):
            unusual_entry.add_observed('Vanilla flow examples', 4, 'Vanilla.bfevfl', 'Event{}'.format(index), {
                'State': 1,
                'Slot': index,
            })
        unusual_entry.add_observed('Current file', 0, 'Current.bfevfl', 'EventOdd', {
            'State': 9,
            'Extra': True,
        })
        notes = unusual_entry.unusual_notes(unusual_entry.all_observed_examples()[-1])
        self.assertTrue(any('Missing usual parameter' in note for note in notes))
        self.assertTrue(any('Extra parameter' in note for note in notes))
        self.assertTrue(any('Rare value' in note for note in notes))
        self.assertEqual(event_library.format_library_value('Playing'), '"Playing"')
        self.assertEqual(event_library.format_library_value('Playing', quote_strings=False), 'Playing')
        example = event_library.EventLibraryExample(
            'Vanilla flow examples',
            'DmF_SY_Test.bfevfl.zs',
            'Event42',
            {},
        )
        self.assertEqual(example.display_name(), 'DmF_SY_Test / Event42')
        self.assertEqual(example.display_label(), 'DmF_SY_Test / Event42 (Vanilla flow examples)')

    def test_event_library_scans_actor_pack_ainb_names_without_parser(self):
        event_library.clear_event_library_cache()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            flow_path = root / 'Event' / 'EventFlow' / 'Current.bfevfl'
            flow_path.parent.mkdir(parents=True)
            pack_path = root / 'Pack' / 'Actor' / 'Player.pack'
            write_sarc(pack_path, {
                'AI/Player.event.root.ainb': (
                    b'header\x00EventTriggerRuntimeOnly\x00EventQueryRuntimeOnly\x00'
                    b'EventPerformer\x00EventStartPos\x00'
                ),
            })

            actions = event_library.build_actor_event_library(
                'Player',
                event_library.EVENT_LIBRARY_ACTION,
                flow_path=str(flow_path),
            )
            queries = event_library.build_actor_event_library(
                'Player',
                event_library.EVENT_LIBRARY_QUERY,
                flow_path=str(flow_path),
            )

            self.assertIn('EventTriggerRuntimeOnly', [entry.name for entry in actions.entries])
            self.assertNotIn('EventQueryRuntimeOnly', [entry.name for entry in actions.entries])
            self.assertIn('EventQueryRuntimeOnly', [entry.name for entry in queries.entries])

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
        tool_root = Path(__file__).resolve().parents[1] / 'tools'
        main_js = Path(util.get_path('assets/main.js')).read_text(encoding='utf-8')
        main_py = (source_root / '__main__.py').read_text(encoding='utf-8')
        flowchart_py = (source_root / 'flowchart_view.py').read_text(encoding='utf-8')
        fake_update_launcher_py = (tool_root / 'launch_fake_update_test.py').read_text(encoding='utf-8')

        self.assertIn('GITHUB_RELEASES_URL', main_py)
        self.assertIn('GITHUB_LATEST_RELEASE_API_URL', main_py)
        self.assertIn('def extract_update_summary', main_py)
        self.assertIn('def build_latest_release_request', main_py)
        self.assertIn('def build_update_info', main_py)
        self.assertIn('class UpdateCheckSignals', main_py)
        self.assertIn('self.update_available_button = q.QToolButton', main_py)
        self.assertIn('self.update_available_button.setText(\'Update available\')', main_py)
        self.assertIn('menu.installEventFilter(self)', main_py)
        self.assertEqual(main_py.count('def eventFilter'), 1)
        self.assertIn('if watched == self.menuBar() and event_type in (qc.QEvent.Resize, qc.QEvent.Show):', main_py)
        self.assertIn('if event_type in (qc.QEvent.DragEnter, qc.QEvent.DragMove, qc.QEvent.Drop):', main_py)
        self.assertIn('def positionUpdateAvailableButton', main_py)
        self.assertIn("self.update_available_button.fontMetrics().horizontalAdvance('Update available') + 16", main_py)
        self.assertIn('self.update_available_button.setGeometry(x, 0, width, height)', main_py)
        self.assertIn('qc.QTimer.singleShot(1500, self.startUpdateCheck)', main_py)
        self.assertIn('threading.Thread(target=self._runUpdateCheck, daemon=True)', main_py)
        self.assertIn('self.update_available_button.setVisible(False)', main_py)
        self.assertIn('self.update_available_button.setVisible(True)', main_py)
        self.assertIn('def dismissedUpdateVersion', main_py)
        self.assertIn('def isUpdateReminderDismissed', main_py)
        self.assertIn('def dismissUpdateReminder', main_py)
        self.assertIn('DISMISSED_UPDATE_VERSION_KEY', main_py)
        self.assertIn("dialog.setWindowTitle('Update available')", main_py)
        self.assertIn('dialog.setMinimumWidth(540)', main_py)
        self.assertIn("q.QCheckBox(\"I like this version, don't remind me again\"", main_py)
        self.assertIn('text_layout.addWidget(dismiss_checkbox)', main_py)
        self.assertNotIn('\n        layout.addWidget(dismiss_checkbox)', main_py)
        self.assertIn("q.QPushButton('Not now'", main_py)
        self.assertIn("q.QPushButton('Go to Releases'", main_py)
        self.assertIn("parser.add_argument('--update-check-url'", main_py)
        self.assertIn("parser.add_argument('--update-check-current-version'", main_py)
        self.assertIn("parser.add_argument('--update-releases-url'", main_py)
        self.assertIn("parser.add_argument('--update-force-reminder'", main_py)
        self.assertIn("parser.add_argument('--smoke-test'", main_py)
        self.assertIn("if self._smoke_test:", main_py)
        self.assertIn('qc.QTimer.singleShot(1000, app.quit)', main_py)
        self.assertIn('self._update_force_reminder or not self.isUpdateReminderDismissed(update_info)', main_py)
        self.assertIn('ThreadingHTTPServer', fake_update_launcher_py)
        self.assertIn("FAKE_LATEST_VERSION = 'v9.9.10-test'", fake_update_launcher_py)
        self.assertIn("'--update-check-url'", fake_update_launcher_py)
        self.assertIn("'--update-releases-url'", fake_update_launcher_py)

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

    def test_linux_build_is_manual_and_experimental(self):
        workflow = (Path(__file__).resolve().parents[1] / '.github' / 'workflows' / 'build-linux-experimental.yml').read_text(encoding='utf-8')
        self.assertIn('name: Build Linux executable (experimental)', workflow)
        self.assertIn('workflow_dispatch:', workflow)
        self.assertNotIn('push:', workflow)
        self.assertIn('runs-on: ubuntu-24.04', workflow)
        self.assertIn('QT_QPA_PLATFORM: offscreen', workflow)
        self.assertIn('QTWEBENGINE_DISABLE_SANDBOX', workflow)
        self.assertIn('libxcb-cursor0', workflow)
        self.assertIn('libxkbcommon-x11-0', workflow)
        self.assertIn('xvfb', workflow)
        self.assertIn('python -m pip install . pyinstaller', workflow)
        self.assertIn('python -m unittest discover -s tests', workflow)
        self.assertIn('--hidden-import PyQt5.QtWebEngineWidgets', workflow)
        self.assertIn('--name "$APP_BUNDLE_NAME"', workflow)
        self.assertIn('xvfb-run -a "dist/$APP_BUNDLE_NAME/$APP_BUNDLE_NAME" --smoke-test', workflow)
        self.assertIn('tar -C dist -czf "$PACKAGE_NAME" "$APP_BUNDLE_NAME"', workflow)
        self.assertIn('TOTK-EventEditor_${safeVersion}-Linux-x86_64', workflow)
        self.assertNotIn('gh release upload', workflow)

    def test_event_chooser_headers_sort_ascending_then_descending(self):
        source_root = Path(__file__).resolve().parents[1] / 'eventeditor'
        event_view_py = (source_root / 'event_view.py').read_text(encoding='utf-8')
        event_chooser_py = (source_root / 'event_chooser_dialog.py').read_text(encoding='utf-8')
        actor_view_py = (source_root / 'actor_view.py').read_text(encoding='utf-8')
        container_view_py = (source_root / 'container_view.py').read_text(encoding='utf-8')
        container_model_py = (source_root / 'container_model.py').read_text(encoding='utf-8')
        event_branch_editors_py = (source_root / 'event_branch_editors.py').read_text(encoding='utf-8')
        event_edit_dialog_py = (source_root / 'event_edit_dialog.py').read_text(encoding='utf-8')
        event_library_py = (source_root / 'event_library.py').read_text(encoding='utf-8')
        event_library_dialog_py = (source_root / 'event_library_dialog.py').read_text(encoding='utf-8')
        flowchart_py = (source_root / 'flowchart_view.py').read_text(encoding='utf-8')
        main_py = (source_root / '__main__.py').read_text(encoding='utf-8')
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
        self.assertIn("q.QPushButton('Library...')", event_edit_dialog_py)
        self.assertIn('build_actor_event_library', event_edit_dialog_py)
        self.assertIn('is_actor_event_library_cache_current', event_edit_dialog_py)
        self.assertIn("self.param_view.addHeaderButton('Add Missing'", event_edit_dialog_py)
        self.assertIn("self.param_view.addHeaderButton('Remove Excess'", event_edit_dialog_py)
        self.assertIn('def onAddMissingParametersRequested', event_edit_dialog_py)
        self.assertIn('def onRemoveExcessParametersRequested', event_edit_dialog_py)
        self.assertIn('def currentLibraryEntry', event_edit_dialog_py)
        self.assertIn('def currentNodeTypeName(self) -> str:', event_edit_dialog_py)
        self.assertIn('self.attr_cbox.currentText().strip()', event_edit_dialog_py)
        self.assertIn("entry.name.strip() == node_name", event_edit_dialog_py)
        self.assertNotIn('refreshed = self.buildLibraryResult(actor, kind)', event_edit_dialog_py)
        self.assertIn('No library entry was found for {}.', event_edit_dialog_py)
        self.assertIn('if not entry.has_vanilla_baseline():', event_edit_dialog_py)
        self.assertIn('vanilla expects no parameters', event_edit_dialog_py)
        self.assertIn('already has no parameters, matching vanilla', event_edit_dialog_py)
        self.assertIn('def cachedLibraryResult', event_edit_dialog_py)
        self.assertIn('def rememberLibraryResult', event_edit_dialog_py)
        self.assertIn('if not force_rebuild and cached_result:', event_edit_dialog_py)
        self.assertIn('result = dialog.exec_()', event_edit_dialog_py)
        self.assertIn('q.QDialogButtonBox.Cancel if apply_enabled else q.QDialogButtonBox.Close', event_edit_dialog_py)
        self.assertIn('self.rememberLibraryResult(actor, kind, result)', event_edit_dialog_py)
        self.assertIn('def promptAddMissingParameters', event_edit_dialog_py)
        self.assertIn("self.param_view.addHeaderButton('Add Missing'", event_edit_dialog_py)
        self.assertIn("button_box.addButton('Add Blank'", event_edit_dialog_py)
        self.assertIn("button_box.addButton('Add All'", event_edit_dialog_py)
        self.assertIn('example_combo = q.QComboBox()', event_edit_dialog_py)
        self.assertIn('entry.all_observed_examples()', event_edit_dialog_py)
        self.assertIn('example_combo.completer().setFilterMode(qc.Qt.MatchContains)', event_edit_dialog_py)
        self.assertIn('example.display_label()', event_edit_dialog_py)
        self.assertIn('def valuesForMissingParameters', event_edit_dialog_py)
        self.assertIn('def actorLibraryLabel(self, actor: Actor, kind: str) -> str:', event_edit_dialog_py)
        self.assertIn("'{} - {}'.format(actor.identifier.name, self.libraryKindLabel(kind))", event_edit_dialog_py)
        self.assertIn('def showLibraryBuildDialog(self, library_label: str) -> q.QDialog:', event_edit_dialog_py)
        self.assertIn('Building library for "{}"...', event_edit_dialog_py)
        self.assertIn('No library entries were found for {}', event_edit_dialog_py)
        self.assertIn('def prepareNodeEditCommit(self) -> None:', event_edit_dialog_py)
        self.assertIn('parent.prepareNodeEditCommit(self.event, self.event_idx)', event_edit_dialog_py)
        self.assertIn('self.prepareNodeEditCommit()', event_edit_dialog_py)
        self.assertNotIn('QProgressDialog', event_edit_dialog_py)
        self.assertIn('def addLibraryEntryToActor', event_edit_dialog_py)
        self.assertIn("self.button_box.addButton('Add to Actor'", event_library_dialog_py)
        self.assertIn("self.button_box.addButton('Rebuild Library'", event_library_dialog_py)
        self.assertIn('self.parameter_table = q.QTableWidget()', event_library_dialog_py)
        self.assertIn("self.tree.setHeaderLabels(['Node type', 'Params', 'Examples', 'Cases', 'File', 'Mod', 'Vanilla'])", event_library_dialog_py)
        self.assertIn('self.tree.header().setStretchLastSection(False)', event_library_dialog_py)
        self.assertIn("self.mod_context_enabled = getattr(result, 'mod_context_enabled', True)", event_library_dialog_py)
        self.assertIn('self.tree.setColumnHidden(5, not self.mod_context_enabled)', event_library_dialog_py)
        self.assertIn('if self.mod_context_enabled and self.mod_examples_check.isChecked():', event_library_dialog_py)
        self.assertIn('{} files were skipped while collecting example values.', event_library_dialog_py)
        self.assertIn('Each row includes the scan stage and the parser/decompression error.', event_library_dialog_py)
        self.assertIn('entry.example_count_label()', event_library_dialog_py)
        self.assertIn('def exampleTooltip', event_library_dialog_py)
        self.assertIn('preview shows up to {} samples', event_library_dialog_py)
        self.assertIn("q.QPushButton('All Uses...')", event_library_dialog_py)
        self.assertIn("q.QCheckBox('Unusual only')", event_library_dialog_py)
        self.assertIn('def selectedSourceGroups', event_library_dialog_py)
        self.assertIn('def filteredExamples', event_library_dialog_py)
        self.assertIn('self.details_bottom_spacer = q.QSpacerItem', event_library_dialog_py)
        self.assertIn('self.details_bottom_spacer.changeSize', event_library_dialog_py)
        self.assertIn('No known parameters or examples.', event_library_dialog_py)
        self.assertIn('goToExampleRequested = qc.pyqtSignal(object)', event_library_dialog_py)
        self.assertIn('self.examples_list.setContextMenuPolicy(qc.Qt.CustomContextMenu)', event_library_dialog_py)
        self.assertIn("menu.addAction('Go to Event')", event_library_dialog_py)
        self.assertNotIn('self.goToExampleRequested.emit(example)\n            self.reject()', event_library_dialog_py)
        self.assertIn('item.setData(qc.Qt.UserRole, example)', event_library_dialog_py)
        self.assertIn('def fitCompactTreeColumns', event_library_dialog_py)
        self.assertIn('def parameterTooltip', event_library_dialog_py)
        self.assertIn('self.case_values = q.QLineEdit()', event_library_dialog_py)
        self.assertIn("self.case_label.setText('Observed switch cases')", event_library_dialog_py)
        self.assertIn('if value is not None:', event_library_dialog_py)
        self.assertIn('font.setItalic(True)', event_library_dialog_py)
        self.assertNotIn("'Summary'", event_library_dialog_py)
        self.assertNotIn('Observed branches', event_library_dialog_py)
        self.assertIn('format_library_value(value, quote_strings=False)', event_library_dialog_py)
        self.assertIn("'Examples:\\n' + '\\n'.join(examples)", event_library_dialog_py)
        self.assertIn('def eventflow_display_name', event_library_py)
        self.assertIn('def _format_scan_error', event_library_py)
        self.assertIn('def _eventflow_skip_reason', event_library_py)
        self.assertIn('def _actor_pack_skip_reason', event_library_py)
        self.assertIn('def is_flow_path_in_vanilla_romfs', event_library_py)
        self.assertIn('def mod_context_enabled_for_flow_path', event_library_py)
        self.assertIn('mod_context_enabled = mod_context_enabled_for_flow_path(flow_path, vanilla_romfs)', event_library_py)
        self.assertIn('Could not parse or decompress EventFlow', event_library_py)
        self.assertIn('Could not decompress or open actor pack archive', event_library_py)
        self.assertIn('def display_label(self) -> str:', event_library_py)
        self.assertIn('self.example_count = 0', event_library_py)
        self.assertIn('def observed_example_count(self) -> int:', event_library_py)
        self.assertIn('def example_count_label(self) -> str:', event_library_py)
        self.assertIn('SOURCE_GROUP_CURRENT', event_library_py)
        self.assertIn('def source_group_for_label', event_library_py)
        self.assertIn('self.all_examples = []', event_library_py)
        self.assertIn('def all_observed_examples(self)', event_library_py)
        self.assertIn('def preview_examples(self', event_library_py)
        self.assertIn('def unusual_notes(self', event_library_py)
        self.assertIn('target.example_count += source_entry.observed_example_count()', event_library_py)
        self.assertIn('_VANILLA_EVENT_LIBRARY_CACHE', event_library_py)
        self.assertIn('_VANILLA_EVENT_LIBRARY_DISK_CACHE_VERSION', event_library_py)
        self.assertIn('TOTK_EVENTEDITOR_LIBRARY_CACHE_DIR', event_library_py)
        self.assertIn('def _read_vanilla_disk_cache', event_library_py)
        self.assertIn('def _write_vanilla_disk_cache', event_library_py)
        self.assertIn('def _build_vanilla_actor_event_library', event_library_py)
        self.assertIn('_write_vanilla_disk_cache(key, result)', event_library_py)
        self.assertIn('def clear_event_library_cache(clear_disk: bool = False) -> None:', event_library_py)
        self.assertIn('_merge_result_into_builders(builders, vanilla_result)', event_library_py)
        self.assertIn('id(current_flow) if current_flow and not flow_path else 0', event_library_py)
        self.assertNotIn('int(current_revision),', event_library_py)
        self.assertNotIn("_eventflow_directory_signature(vanilla_root / 'Event' / 'EventFlow')", event_library_py)
        self.assertIn("'Vanilla actor file'", event_library_py)
        self.assertIn('def seed_value_for_sources', event_library_py)
        self.assertIn('def vanilla_parameter_names', event_library_py)
        self.assertIn('def has_vanilla_baseline(self) -> bool:', event_library_py)
        self.assertIn('def is_actor_event_library_cache_current', event_library_py)
        self.assertIn('EVENT_LIBRARY_ACTION', event_library_py)
        self.assertIn('def prepareNodeEditCommit(self, event: Event, node_id: int) -> None:', flowchart_py)
        self.assertIn('self.selected_event = event', flowchart_py)
        self.assertIn('self.pending_reveal_event = event', flowchart_py)
        self.assertIn('libraryExampleOpenRequested = qc.pyqtSignal(str, str)', flowchart_py)
        self.assertIn('def goToLibraryExample(self, example) -> None:', flowchart_py)
        self.assertIn('def selectEventByName(self, event_name: str', flowchart_py)
        self.assertIn('self.libraryExampleOpenRequested.emit(source_file, event_name)', flowchart_py)
        self.assertIn("parser.add_argument('--event'", main_py)
        self.assertIn("launch_args.extend(['--event', event_name])", main_py)
        self.assertIn('def selectStartupEventIfRequested(self) -> None:', main_py)
        self.assertIn('def onOpenLibraryExampleRequested(self, source_file: str, event_name: str) -> None:', main_py)
        self.assertIn('self.flowchart_view.libraryExampleOpenRequested.connect(self.onOpenLibraryExampleRequested)', main_py)
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
