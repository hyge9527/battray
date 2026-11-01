"""Evidence and next actions, never a source of guessed vendor commands."""

from .registry import REVIEWED_ADAPTERS
from ..platform.installation import ACCESS_POLICIES, render_rule


def assess(info):
    matches = []
    for adapter in REVIEWED_ADAPTERS:
        match = adapter.match(info['devices'])
        policy = next((p for p in ACCESS_POLICIES if p.profile.profile_id == adapter.profile.profile_id), None)
        matches.append(dict(profile_id=match.profile_id, name=adapter.profile.display_name,
                            status=match.status.value, reason=match.reason,
                            automatic_read_allowed=match.automatic_read_allowed,
                            rule=render_rule(policy) if policy and match.automatic_read_allowed else None))
    return dict(version=1, target=info['target'], matches=matches,
                devices=info['devices'],
                next_step='支持档案仍需节点权限与设备实测；未知设备只收集证据，不发送候选命令',
                permission_install='已支持档案才可显式 sudo 运行 tools/install_device_access.py；常驻程序不以 root 运行')
