"""Reviewed access policy, rendered from the same profile as device matching."""

from dataclasses import dataclass
import re

from ..adapters.profiles import F98PRO
from ..domain.matching import DeviceProfile, match_profile


@dataclass(frozen=True)
class AccessPolicy:
    profile: DeviceProfile
    marker: str
    filename: str
    description: str


F98_ACCESS = AccessPolicy(F98PRO, 'aula-f98pro', '70-keyboard-power.rules', 'local F98Pro receiver profile')
ACCESS_POLICIES = (F98_ACCESS,)


def render_rule(policy):
    profile = policy.profile
    for value in (profile.vid, profile.pid, profile.product, profile.interface, policy.marker):
        if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9 ._-]+', value):
            raise ValueError('权限规则字段含不允许的模式或控制字符')
    lines = ['# Optional, reviewed ' + policy.description + '. Install explicitly as root.',
             "# Place before Ubuntu's 73-seat-late.rules so uaccess can grant the active user ACL.",
             '# Separate rules intentionally match USB-device and interface ancestors separately.']
    for revision in sorted(profile.supported_revisions):
        if not re.fullmatch(r'[0-9A-Fa-f]{4}', revision):
            raise ValueError('权限规则 USB 版本无效')
        lines.append(f'SUBSYSTEM=="hidraw", ATTRS{{idVendor}}=="{profile.vid.lower()}", ATTRS{{idProduct}}=="{profile.pid.lower()}", ATTRS{{product}}=="{profile.product}", ATTRS{{bcdDevice}}=="{revision}", ENV{{KEYBOARD_POWER_RECEIVER}}="{policy.marker}"')
    lines.append(f'SUBSYSTEM=="hidraw", ENV{{KEYBOARD_POWER_RECEIVER}}=="{policy.marker}", ATTRS{{bInterfaceNumber}}=="{profile.interface}", TAG+="uaccess"')
    return '\n'.join(lines) + '\n'


def select_access(devices):
    candidates = [(policy, match_profile(policy.profile, devices)) for policy in ACCESS_POLICIES]
    candidates = [(policy, match) for policy, match in candidates if match.automatic_read_allowed]
    if len(candidates) != 1:
        raise ValueError('需要唯一已验证档案的接收器；拒绝安装权限规则')
    policy, match = candidates[0]
    return policy, devices[match.index]
