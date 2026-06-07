import tempfile
import unittest
from pathlib import Path

from evfl import EventFlow, Flowchart

from eventeditor.__main__ import normalize_flow_save_path
import eventeditor.actor_xml as actor_xml
import eventeditor.container_xml as container_xml
import eventeditor.entry_point_tree_xml as entry_point_tree_xml
import eventeditor.mals as mals
import eventeditor.totk_zs as totk_zs
import eventeditor.util as util


class ReconstructedQoLTests(unittest.TestCase):
    def test_totk_suffix_helpers(self):
        self.assertEqual(
            normalize_flow_save_path('Demo', 'Compressed TotK flowchart .bfevfl.zs (*)'),
            'Demo.bfevfl.zs',
        )
        self.assertTrue(totk_zs.is_compressed_path('Demo.bfevfl.zs'))
        self.assertTrue(totk_zs.is_compressed_path('Demo.bfevfl.zstd'))
        self.assertFalse(totk_zs.is_compressed_path('Demo.bfevfl'))

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

    def test_packaged_assets_resolve(self):
        for asset in [
            'assets/main.js',
            'assets/main.css',
            'assets/index.html',
            'assets/material_visibility_24.svg',
            'assets/material_visibility_off_24.svg',
        ]:
            self.assertTrue(Path(util.get_path(asset)).is_file(), asset)

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
