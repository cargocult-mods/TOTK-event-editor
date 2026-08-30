import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def load_workflow(name):
    path = ROOT / '.github' / 'workflows' / name
    return path.read_text(encoding='utf-8'), yaml.load(
        path.read_text(encoding='utf-8'),
        Loader=yaml.BaseLoader,
    )


class ReleaseWorkflowTests(unittest.TestCase):
    def test_release_archives_keep_versioned_download_names_but_stable_install_names(self):
        windows_source, _ = load_workflow('build-windows.yml')
        linux_source, _ = load_workflow('build-linux-experimental.yml')

        self.assertIn('$appBundleName = "TOTK Event Editor"', windows_source)
        self.assertIn('$artifactName = "TOTK-EventEditor_${safeVersion}-Windows"', windows_source)
        self.assertIn(
            'Compress-Archive -Path "dist/$env:APP_BUNDLE_NAME"',
            windows_source,
        )
        self.assertNotIn(
            'Compress-Archive -Path "dist/$env:APP_BUNDLE_NAME/*"',
            windows_source,
        )

        self.assertIn('appBundleName="TOTK Event Editor"', linux_source)
        self.assertIn('artifactName="TOTK-EventEditor_${safeVersion}-Linux-x86_64"', linux_source)
        self.assertIn(
            'tar -C dist -czf "$PACKAGE_NAME" "$APP_BUNDLE_NAME"',
            linux_source,
        )

    def test_linux_build_runs_for_tags_and_attaches_a_release_asset(self):
        source, workflow = load_workflow('build-linux-experimental.yml')

        self.assertEqual(workflow['name'], 'Build Linux executable')
        self.assertEqual(workflow['on']['push']['tags'], ['v*'])
        self.assertIn('workflow_dispatch', workflow['on'])
        self.assertEqual(workflow['permissions']['contents'], 'write')
        self.assertIn('Remove test-build metadata', source)
        self.assertIn('TOTK-EventEditor_${safeVersion}-Linux-x86_64', source)
        self.assertIn('xvfb-run -a "dist/$APP_BUNDLE_NAME/$APP_BUNDLE_NAME" --smoke-test', source)
        self.assertIn('gh release upload "$tag" "$PACKAGE_NAME" --clobber', source)

    def test_production_workflows_strip_test_build_metadata(self):
        windows_source, _ = load_workflow('build-windows.yml')
        linux_source, _ = load_workflow('build-linux-experimental.yml')

        metadata_path = 'eventeditor/assets/test_build_info.json'
        self.assertIn(metadata_path, windows_source)
        self.assertIn(metadata_path, linux_source)

    def test_windows_release_upload_is_safe_if_linux_creates_the_release_first(self):
        source, _workflow = load_workflow('build-windows.yml')

        self.assertIn('gh release create $tag --title $tag --generate-notes', source)
        self.assertIn('gh release upload $tag "$env:PACKAGE_NAME" --clobber', source)
        self.assertNotIn('gh release create $tag "$env:PACKAGE_NAME"', source)


if __name__ == '__main__':
    unittest.main()
