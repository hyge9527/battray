"""Explicit user settings and XDG launchers. Never modifies settings on read."""

from pathlib import Path
import os
import shlex
import sys


APP_ID = 'local.keyboard-power'
PROJECT = Path(__file__).resolve().parent.parent


def config_home():
    candidate = Path(os.environ.get('XDG_CONFIG_HOME', ''))
    return candidate if candidate.is_absolute() else Path.home() / '.config'


def settings_path():
    return config_home() / APP_ID / 'settings.json'


def load_settings():
    from .config.store import load
    return load(settings_path())


def save_interval(interval):
    from .config.store import update
    update(settings_path(), interval=interval)


def desktop_directory():
    for line in (config_home() / 'user-dirs.dirs').read_text().splitlines():
        if line.startswith('XDG_DESKTOP_DIR='):
            words = shlex.split(line.split('=', 1)[1], comments=True)
            if len(words) == 1:
                value = words[0].replace('${HOME}', str(Path.home())).replace('$HOME', str(Path.home()))
                directory = Path(value)
                if directory.is_absolute() and directory != Path.home():
                    return directory
    raise ValueError('未找到有效 XDG 桌面目录，请先在系统中配置桌面目录')


def exec_quote(value):
    # Desktop Entry Exec uses its own quoting and a second string unescape pass.
    value = str(value)
    if any(c in value for c in '\n\r\x00'):
        raise ValueError('启动路径不能含控制字符')
    value = value.replace('%', '%%').replace('\\', '\\\\\\\\')
    for char in ('"', '`', '$'):
        value = value.replace(char, '\\\\' + char)
    return '"' + value + '"'


def launcher_text():
    return ('[Desktop Entry]\nType=Application\nName=键盘电量托盘\n'
            'Comment=AULA F98Pro 无线键盘电量\nTerminal=false\n'
            'Categories=Utility;\nIcon=input-keyboard\n'
            f'Exec={exec_quote(sys.executable)} -B {exec_quote(PROJECT / "my_devices.py")} --tray\n')


def autostart_path():
    return config_home() / 'autostart' / (APP_ID + '.desktop')


def autostart_status():
    path = autostart_path()
    if not path.exists():
        return False, '未配置登录自启'
    text = path.read_text()
    entries = dict(line.split('=', 1) for line in text.splitlines() if '=' in line and not line.startswith('#'))
    if entries.get('Hidden', 'false').lower() == 'true' or entries.get('X-GNOME-Autostart-enabled', 'true').lower() == 'false':
        return False, '登录自启已禁用'
    expected = next(line[5:] for line in launcher_text().splitlines() if line.startswith('Exec='))
    if entries.get('Exec') != expected or entries.get('OnlyShowIn') or entries.get('NotShowIn') or entries.get('AutostartCondition'):
        return False, '自启配置已变更或带外部条件，请检查启动项'
    return True, '已配置登录自启（实际启动依赖桌面会话）'


def set_autostart(enabled):
    path = autostart_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    text = launcher_text() + ('Hidden=false\nX-GNOME-Autostart-enabled=true\n' if enabled
                              else 'Hidden=true\nX-GNOME-Autostart-enabled=false\n')
    path.write_text(text)
    return path


def install_desktop():
    directory = desktop_directory()
    if not directory.is_dir():
        raise ValueError(f'桌面目录不存在：{directory}')
    launcher = PROJECT / (APP_ID + '.desktop')
    expected = launcher_text()
    if launcher.exists() and launcher.read_text() != expected:
        raise ValueError(f'项目启动器内容不同，请人工检查：{launcher}')
    links = {'键盘电量项目': PROJECT, 'my_devices.py': PROJECT / 'my_devices.py',
             '键盘电量.desktop': launcher}
    for name, target in links.items():
        path = directory / name
        if os.path.lexists(path) and not (path.is_symlink() and path.resolve() == target.resolve()):
            raise ValueError(f'拒绝覆盖已有桌面文件：{path}')
    launcher.write_text(expected)
    launcher.chmod(0o755)
    for name, target in links.items():
        path = directory / name
        if not os.path.lexists(path):
            path.symlink_to(target, target_is_directory=target.is_dir())
    return [str(directory / name) for name in links]
