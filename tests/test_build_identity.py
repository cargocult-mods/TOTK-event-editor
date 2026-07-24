import json
import tempfile
import unittest
from pathlib import Path

from eventeditor.build_identity import (
    build_about_version_html,
    load_test_build_info,
)


class BuildIdentityTests(unittest.TestCase):
    def test_production_about_reports_only_the_version(self):
        html = build_about_version_html('v1.3.4', None)

        self.assertIn('Version: v1.3.4', html)
        self.assertNotIn('beta', html)
        self.assertNotIn('built', html)
        self.assertNotIn('Intended new features', html)

    def test_test_build_about_reports_beta_timestamp_and_features(self):
        html = build_about_version_html(
            'v1.3.4',
            {
                'beta': 'beta4',
                'built_at': '24/7/2026 11:57am',
                'intended_features': [
                    'Audited switch branch labels',
                    'Actor safety defaults and save repair',
                ],
            },
        )

        self.assertIn('Version: v1.3.4 beta4, built 24/7/2026 11:57am', html)
        self.assertIn('Intended new features:', html)
        self.assertIn('<li>Audited switch branch labels</li>', html)
        self.assertIn('<li>Actor safety defaults and save repair</li>', html)

    def test_test_build_text_is_html_escaped(self):
        html = build_about_version_html(
            'v1.3.4',
            {
                'beta': 'beta<script>',
                'built_at': 'now',
                'intended_features': ['A < B'],
            },
        )

        self.assertNotIn('<script>', html)
        self.assertIn('beta&lt;script&gt;', html)
        self.assertIn('A &lt; B', html)

    def test_invalid_or_absent_metadata_is_treated_as_production(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'test_build_info.json'
            self.assertIsNone(load_test_build_info(path))

            path.write_text('{bad json', encoding='utf-8')
            self.assertIsNone(load_test_build_info(path))

            path.write_text(json.dumps({'beta': 'beta4'}), encoding='utf-8')
            self.assertIsNone(load_test_build_info(path))

            valid = {
                'beta': 'beta4',
                'built_at': '24/7/2026 11:57am',
                'intended_features': ['Feature one'],
            }
            path.write_text(json.dumps(valid), encoding='utf-8')
            self.assertEqual(load_test_build_info(path), valid)


if __name__ == '__main__':
    unittest.main()
