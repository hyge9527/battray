#!/usr/bin/env python3
"""Explicit per-user GNOME 46 extension install; no shell restart or root use."""

import ast
import json
import os
from pathlib import Path
import subprocess

UUID = 'keyboard-power-position@local'
SOURCE = Path(__file__).resolve().parent.parent / 'packaging/gnome-tray-position'


def main():
    if os.geteuid() == 0:
        raise RuntimeError('请以桌面普通用户运行，不使用 sudo')
    version = subprocess.run(['gnome-shell', '--version'], capture_output=True, text=True, check=True).stdout
    if not version.startswith('GNOME Shell 46.'):
        raise RuntimeError('该扩展仅针对已核对的本机 GNOME Shell 46')
    data_home = Path(os.environ.get('XDG_DATA_HOME', ''))
    if not data_home.is_absolute():
        data_home = Path.home() / '.local/share'
    destination = data_home / 'gnome-shell/extensions' / UUID
    payload = {name: (SOURCE / name).read_bytes() for name in ('metadata.json', 'extension.js')}
    if destination.is_symlink():
        raise RuntimeError('拒绝写入符号链接扩展目录')
    if destination.exists():
        if set(p.name for p in destination.iterdir()) != set(payload):
            raise RuntimeError('已有扩展目录内容不同，拒绝覆盖')
        for name, content in payload.items():
            if (destination / name).is_symlink() or (destination / name).read_bytes() != content:
                raise RuntimeError('已有扩展文件内容不同，拒绝覆盖')
    settings = subprocess.run(['gsettings', 'get', 'org.gnome.shell', 'enabled-extensions'],
                              capture_output=True, text=True, check=True).stdout.strip()
    enabled = ast.literal_eval(settings.removeprefix('@as '))
    if not isinstance(enabled, list) or not all(isinstance(item, str) for item in enabled):
        raise RuntimeError('无法解析已启用扩展列表，未修改')
    destination.mkdir(parents=True, exist_ok=True)
    for name, content in payload.items():
        path = destination / name
        if not path.exists():
            with path.open('xb') as stream:
                stream.write(content)
    if UUID not in enabled:
        subprocess.run(['gsettings', 'set', 'org.gnome.shell', 'enabled-extensions', json.dumps(enabled + [UUID])], check=True)
    # GNOME can require a new login before discovering a newly installed local
    # extension. Do not restart GNOME or log out the user to force discovery.
    result = subprocess.run(['gnome-extensions', 'enable', UUID], capture_output=True, text=True)
    print('已安装：' + str(destination))
    print('已加入启用列表；' + ('已请求当前会话启用。' if result.returncode == 0 else '当前会话尚未识别，请保存工作后注销并重新登录。'))
    print('撤销：gnome-extensions disable ' + UUID)


if __name__ == '__main__':
    main()
