"""Read without migration; explicitly write atomically, retaining unknown fields."""

import json
import os
import tempfile

from .bindings import bindings_document, parse_bindings


def _validate(data):
    if not isinstance(data, dict):
        raise ValueError('设置文件须为 JSON 对象')
    if 'version' in data or 'kind' in data:
        if type(data.get('version')) is not int or data['version'] != 2 or data.get('kind') != 'keyboard-power-settings':
            raise ValueError('设置文件版本不支持，拒绝迁移或覆盖')
    if 'bindings' in data:
        parse_bindings(dict(kind='keyboard-power-bindings', version=1, devices=data['bindings']))
    return data


def load(path):
    try:
        text = path.read_text()
    except FileNotFoundError:
        return {'interval': 60}
    try:
        data = json.loads(text)
    except ValueError:
        # Keep the historical read fallback; explicit writes still refuse it.
        return {'interval': 60}
    data = dict(_validate(data))
    interval = data.get('interval')
    data['interval'] = interval if type(interval) is int and 30 <= interval <= 1800 else 60
    return data


def update(path, *, interval=None, targets=None, clear_bindings=False):
    if interval is not None and (type(interval) is not int or not 30 <= interval <= 1800):
        raise ValueError('刷新间隔必须为 30～1800 秒')
    try:
        previous = path.read_bytes()
    except FileNotFoundError:
        previous = None
    data = _validate(json.loads(previous)) if previous is not None else {}
    data = dict(data)
    if targets is not None:
        document = bindings_document(targets)
        parse_bindings(document)
        data['bindings'] = document['devices']
    if clear_bindings:
        data.pop('bindings', None)
    if interval is not None:
        data['interval'] = interval
    data.update(kind='keyboard-power-settings', version=2)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Preserve the original legacy file before the first explicit migration.
    if previous is not None and 'version' not in json.loads(previous):
        backup = path.with_name('settings.before-v2.json')
        try:
            fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
        except FileExistsError:
            pass  # Never overwrite the user's first migration baseline.
        else:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(previous)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, prefix='settings-', suffix='.tmp', delete=False) as stream:
            temporary = stream.name
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and os.path.exists(temporary):
            os.unlink(temporary)
