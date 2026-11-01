import json
from pathlib import Path

from ..application.service import Target


def parse_bindings(document):
    if (not isinstance(document, dict) or document.get('kind') != 'keyboard-power-bindings'
            or type(document.get('version')) is not int or document['version'] != 1
            or set(document) != {'kind', 'version', 'devices'}):
        raise ValueError('需要 kind=keyboard-power-bindings、version=1 的设备绑定文件；标定 JSON 不能用于后台')
    devices = document['devices']
    if not isinstance(devices, list) or not 1 <= len(devices) <= 16:
        raise ValueError('设备绑定数量须为 1～16')
    targets = []
    for device in devices:
        if (not isinstance(device, dict) or not {'binding_id', 'vid', 'pid', 'name'} <= set(device)
                or set(device) - {'binding_id', 'vid', 'pid', 'name', 'usb_path'}):
            raise ValueError('设备绑定只接受 binding_id/vid/pid/name/usb_path，不接受请求或脚本')
        target = Target(**device)
        for previous in targets:
            if target.binding_id == previous.binding_id:
                raise ValueError('设备绑定 ID 重复')
            if ((target.vid, target.pid) == (previous.vid, previous.pid)
                    and (not target.usb_path or not previous.usb_path or target.usb_path == previous.usb_path)):
                raise ValueError('同 VID/PID 设备须分别绑定不同的 usb_path，不能重叠选择')
        targets.append(target)
    return targets


def bindings_document(targets):
    return dict(kind='keyboard-power-bindings', version=1,
                devices=[dict(binding_id=t.binding_id, vid=t.vid, pid=t.pid,
                              name=t.name, usb_path=t.usb_path) for t in targets])


def load_bindings(path):
    return parse_bindings(json.loads(Path(path).read_text()))
