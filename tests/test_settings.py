from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import os
import unittest

from keyboard_power import settings


class SettingsTests(unittest.TestCase):
    def test_autostart_read_never_creates_and_respects_system_disable(self):
        with TemporaryDirectory() as directory, patch.dict(os.environ, {'XDG_CONFIG_HOME': directory}):
            self.assertFalse(settings.autostart_status()[0])
            self.assertEqual(list(Path(directory).iterdir()), [])
            settings.set_autostart(True)
            self.assertTrue(settings.autostart_status()[0])
            path = settings.autostart_path()
            path.write_text(path.read_text().replace('Hidden=false', 'Hidden=true'))
            before = path.read_bytes()
            self.assertFalse(settings.autostart_status()[0])
            self.assertEqual(path.read_bytes(), before)

    def test_desktop_links_resolve_to_project_without_copy_or_overwrite(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            project, desktop = root / 'project folder', root / '桌面'
            project.mkdir()
            desktop.mkdir()
            (project / 'my_devices.py').write_text('# source\n')
            with patch.object(settings, 'PROJECT', project), patch.object(settings, 'desktop_directory', return_value=desktop):
                links = settings.install_desktop()
                self.assertTrue(all(Path(p).is_symlink() for p in links))
                script = desktop / 'my_devices.py'
                self.assertEqual(script.resolve(), project / 'my_devices.py')
                settings.install_desktop()  # idempotent
                script.unlink()
                script.write_text('user content')
                with self.assertRaises(ValueError):
                    settings.install_desktop()
                self.assertEqual(script.read_text(), 'user content')

    def test_xdg_directory_is_parsed_without_executing_shell(self):
        with TemporaryDirectory() as directory, patch.dict(os.environ, {'XDG_CONFIG_HOME': directory}):
            Path(directory, 'user-dirs.dirs').write_text('XDG_DESKTOP_DIR="$HOME/桌面"\n')
            self.assertEqual(settings.desktop_directory(), Path.home() / '桌面')

    def test_interval_validation_and_exec_field_codes(self):
        with TemporaryDirectory() as directory, patch.dict(os.environ, {'XDG_CONFIG_HOME': directory}):
            for interval in (0, 29, 1801, True, '60'):
                with self.assertRaises(ValueError):
                    settings.save_interval(interval)
            settings.save_interval(90)
            self.assertEqual(settings.load_settings()['interval'], 90)
            self.assertEqual(settings.exec_quote('/tmp/a b%f'), '"/tmp/a b%%f"')
            with self.assertRaises(ValueError):
                settings.exec_quote('/tmp/a\nb')
