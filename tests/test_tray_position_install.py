from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import install_tray_position as installer


class TrayPositionInstallTests(unittest.TestCase):
    def run_install(self, directory, enabled):
        calls = []
        def run(argv, **kwargs):
            calls.append(argv)
            if argv == ['gnome-shell', '--version']:
                return SimpleNamespace(stdout='GNOME Shell 46.0\n', returncode=0)
            if argv[:2] == ['gsettings', 'get']:
                return SimpleNamespace(stdout=repr(enabled), returncode=0)
            return SimpleNamespace(stdout='', returncode=1 if argv[0] == 'gnome-extensions' else 0)
        with patch.dict(os.environ, XDG_DATA_HOME=directory), patch.object(installer.os, 'geteuid', return_value=1000), \
                patch.object(installer.subprocess, 'run', side_effect=run), redirect_stdout(io.StringIO()):
            installer.main()
        return calls

    def test_only_own_extension_added_and_existing_extensions_preserved(self):
        with TemporaryDirectory() as directory:
            calls = self.run_install(directory, ['existing-one', 'existing-two'])
            writes = [call for call in calls if call[:2] == ['gsettings', 'set']]
            self.assertEqual(len(writes), 1)
            self.assertEqual(json.loads(writes[0][-1]), ['existing-one', 'existing-two', installer.UUID])
            destination = Path(directory) / 'gnome-shell/extensions' / installer.UUID
            for name in ('metadata.json', 'extension.js'):
                self.assertEqual((destination / name).read_bytes(), (installer.SOURCE / name).read_bytes())

    def test_reinstall_is_idempotent_and_never_rewrites_enabled_list(self):
        with TemporaryDirectory() as directory:
            self.run_install(directory, [installer.UUID])
            calls = self.run_install(directory, [installer.UUID])
            self.assertFalse(any(call[:2] == ['gsettings', 'set'] for call in calls))

    def test_modified_extension_refused_without_overwrite_or_settings_write(self):
        with TemporaryDirectory() as directory:
            self.run_install(directory, [])
            path = Path(directory) / 'gnome-shell/extensions' / installer.UUID / 'extension.js'
            path.write_text('user modification')
            with self.assertRaises(RuntimeError):
                self.run_install(directory, [])
            self.assertEqual(path.read_text(), 'user modification')
