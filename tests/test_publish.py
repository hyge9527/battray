import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tools.prepare_github import prepare


class PublishExportTests(unittest.TestCase):
    def test_export_excludes_local_artifacts_and_verifies_copied_content(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'my_devices.py').write_text('# entry\n')
            (root / 'README.md').write_text('# project\n')
            (root / 'local.keyboard-power.desktop').write_text('/private/local/path')
            (root / '.env').write_text('not-for-export')
            (root / '.backups').mkdir()
            (root / '.backups/private.md').write_text('local backup')
            (root / 'docs').mkdir()
            (root / 'docs/usage.md').write_text('usage')
            (root / 'docs/review-baseline.json').write_text('{"local":true}')
            (root / 'tests').mkdir()
            (root / 'tests/test_example.py').write_text('# test\n')
            output, manifest = prepare(root)
            names = {item['path'] for item in manifest['files']}
            self.assertEqual(names, {'my_devices.py', 'README.md', 'docs/usage.md', 'tests/test_example.py'})
            for item in manifest['files']:
                self.assertEqual(hashlib.sha256((output / item['path']).read_bytes()).hexdigest(), item['sha256'])
            self.assertFalse((output / '.git').exists())
            self.assertFalse(manifest['license_present'])

    def test_source_symlink_refused_before_exporting(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'my_devices.py').write_text('# entry\n')
            (root / 'tools').mkdir()
            (root / 'outside.py').write_text('not to follow')
            (root / 'tools/linked.py').symlink_to(root / 'outside.py')
            with self.assertRaises(ValueError):
                prepare(root)
            self.assertFalse((root / '.publish').exists())

    def test_publish_symlink_refused_without_writing_target(self):
        with TemporaryDirectory() as directory, TemporaryDirectory() as destination:
            root = Path(directory)
            (root / 'my_devices.py').write_text('# entry\n')
            (root / '.publish').symlink_to(destination, target_is_directory=True)
            with self.assertRaises(ValueError):
                prepare(root)
            self.assertEqual(list(Path(destination).iterdir()), [])
