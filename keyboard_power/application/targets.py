"""Resolve explicit one-run choices before persisted device bindings."""

from .registry import REVIEWED_ADAPTERS
from .service import Target


def targets_for_args(args):
    from ..config.bindings import load_bindings, parse_bindings
    if getattr(args, 'targets_config', None):
        return load_bindings(args.targets_config)
    if getattr(args, 'use_saved_targets', False) and not getattr(args, 'selection_explicit', False):
        from ..settings import load_settings
        data = load_settings()
        if 'bindings' in data:
            return parse_bindings(dict(kind='keyboard-power-bindings', version=1, devices=data['bindings']))
    name = next((a.profile.display_name for a in REVIEWED_ADAPTERS
                 if (a.profile.vid, a.profile.pid) == (args.vid, args.pid)), '无线设备')
    return [Target(vid=args.vid, pid=args.pid, usb_path=args.usb_path, name=name)]


def selectors(targets):
    return [dict(binding_id=t.binding_id, vid=t.vid, pid=t.pid, usb_path=t.usb_path) for t in targets]
