import importlib.util
from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / 'eventeditor' / 'query_case_labels.py'


class QueryCaseLabelTests(unittest.TestCase):
    def load_module(self):
        self.assertTrue(MODULE_PATH.is_file(), 'query_case_labels.py is missing')
        spec = importlib.util.spec_from_file_location('query_case_labels', MODULE_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_engine_audited_query_case_labels(self):
        labels = self.load_module()

        self.assertEqual(
            labels.audited_case_label('GameDataActor', 'EventQueryIsGameDataInt', 0),
            '0 (is less than)',
        )
        self.assertEqual(
            labels.audited_case_label('GameDataActor', 'EventQueryIsGameDataInt', 1),
            '1 (equal)',
        )
        self.assertEqual(
            labels.audited_case_label('GameDataActor', 'EventQueryIsGameDataInt', 2),
            '2 (is more than)',
        )
        self.assertEqual(
            labels.audited_case_label('GameDataActor', 'EventQueryIsGameDataFloat', 2),
            '2 (is more than)',
        )
        self.assertEqual(
            labels.audited_case_label('GameDataActor', 'EventQueryIsGameDataEnum', 1),
            '1 (not equal)',
        )
        self.assertEqual(
            labels.audited_case_label('GameDataActor', 'EventQueryIsGameDataString64', 0),
            '0 (equal)',
        )
        self.assertEqual(
            labels.audited_case_label('GameSystemActor', 'EventQueryTalkChoice4', 3),
            '3 (choice 4)',
        )
        self.assertEqual(
            labels.audited_case_label(
                'EventWorldManagerController', 'EventQueryTimeDivision', 6
            ),
            '6 (night A, 21:00+)',
        )
        self.assertEqual(
            labels.audited_case_label(
                'PouchSystemActor', 'EventQueryCheckSellResult', 2
            ),
            '2 (cannot sell: equipped)',
        )

    def test_unknown_query_or_case_keeps_numeric_label(self):
        labels = self.load_module()

        self.assertIsNone(
            labels.audited_case_label('GameDataActor', 'EventQueryUnknown', 0)
        )
        self.assertIsNone(
            labels.audited_case_label('GameDataActor', 'EventQueryIsGameDataInt', 99)
        )
        self.assertIsNone(
            labels.audited_case_label('GameDataActor', 'EventQueryIsGameDataInt', 'x')
        )


if __name__ == '__main__':
    unittest.main()
