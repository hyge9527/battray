"""Per-user single-instance lock and small local command channel."""

import fcntl
import json
import os
from pathlib import Path
import socket
import stat

from .settings import APP_ID


def runtime_directory():
    path = Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}'))
    metadata = path.stat()
    if not path.is_absolute() or metadata.st_uid != os.getuid() or metadata.st_mode & 0o077:
        raise RuntimeError('XDG_RUNTIME_DIR 必须由当前用户拥有，且仅本人可访问')
    return path


def command(action, **parameters):
    path = runtime_directory() / (APP_ID + '.sock')
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(3)
        client.connect(str(path))
        client.sendall(json.dumps({'action': action, **parameters}).encode() + b'\n')
        data = bytearray()
        while b'\n' not in data:
            part = client.recv(4096)
            if not part:
                raise RuntimeError('已有实例未返回结果')
            data.extend(part)
            if len(data) > 65536:
                raise RuntimeError('IPC 返回过长')
    return json.loads(data.split(b'\n', 1)[0])


class Instance:
    def __init__(self):
        self.directory = runtime_directory()
        self.path = self.directory / (APP_ID + '.sock')
        self.lock_fd = os.open(self.directory / (APP_ID + '.lock'), os.O_CREAT | os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
        self.socket = None
        try:
            fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(self.lock_fd)
            self.lock_fd = None
            raise
        try:
            if os.path.lexists(self.path):
                metadata = self.path.lstat()
                if not stat.S_ISSOCK(metadata.st_mode) or metadata.st_uid != os.getuid():
                    raise RuntimeError('拒绝替换不属于本工具的 IPC 路径')
                self.path.unlink()
            self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.socket.bind(str(self.path))
            self.path.chmod(0o600)
            self.inode = self.path.stat().st_ino
            self.socket.listen(4)
            self.socket.setblocking(False)
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.socket is not None:
            self.socket.close()
            self.socket = None
            if self.path.exists() and self.path.stat().st_ino == getattr(self, 'inode', None):
                self.path.unlink()
        if self.lock_fd is not None:
            os.close(self.lock_fd)
            self.lock_fd = None
