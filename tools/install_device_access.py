#!/usr/bin/env python3
"""Explicit root-only install of the reviewed, narrowly matched uaccess rule.

Does not run the GUI, change device ownership/mode, or send HID commands.
"""

import os
from pathlib import Path
import subprocess
import sys

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))
from keyboard_power.platform.installation import render_rule, select_access
from keyboard_power.hid import enumerate_hid


def main():
    if os.geteuid() != 0:
        raise RuntimeError('请使用 sudo 显式运行本安装脚本；常驻程序仍以普通用户运行')
    policy, device = select_access(enumerate_hid())
    source = PROJECT / 'packaging' / policy.filename
    destination = Path('/etc/udev/rules.d') / policy.filename
    text = render_rule(policy)
    if source.read_text() != text:
        raise RuntimeError('项目权限规则与已审阅档案不一致，拒绝安装')
    if destination.exists() and destination.read_text() != text:
        raise RuntimeError(f'已有不同内容的规则，拒绝覆盖：{destination}')
    subprocess.run(['/usr/bin/udevadm', 'verify', str(source)], check=True)
    destination.write_text(text)
    destination.chmod(0o644)
    subprocess.run(['/usr/bin/udevadm', 'control', '--reload-rules'], check=True)
    sys_path = str(Path(device['hid_path']) / 'hidraw' / Path(device['node']).name)
    subprocess.run(['/usr/bin/udevadm', 'trigger', '--action=add', sys_path], check=True)
    subprocess.run(['/usr/bin/udevadm', 'settle', '--timeout=5'], check=True)
    print(f'已安装 {destination}；仅为匹配的 F98Pro 接收器接口 03 添加活动用户 uaccess 授权。')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(2)
