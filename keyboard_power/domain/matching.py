from dataclasses import dataclass
from enum import Enum

from .identity import InterfaceIdentity


class MatchStatus(str, Enum):
    SUPPORTED = 'supported'
    NO_MATCH = 'no_match'
    UNSUPPORTED_VERSION = 'unsupported_version'
    AMBIGUOUS = 'ambiguous'
    CANDIDATE = 'candidate'


@dataclass(frozen=True)
class DeviceProfile:
    profile_id: str
    display_name: str
    vid: str
    pid: str
    product: str
    interface: str
    descriptor_hex: str
    supported_revisions: frozenset[str]
    reviewed: bool = True

    def has_shape(self, identity):
        return all(getattr(identity, key) == getattr(self, key)
                   for key in ('vid', 'pid', 'product', 'interface', 'descriptor_hex'))


@dataclass(frozen=True)
class MatchResult:
    profile_id: str
    status: MatchStatus
    reason: str
    candidate_indices: tuple[int, ...] = ()

    @property
    def automatic_read_allowed(self):
        return self.status is MatchStatus.SUPPORTED

    @property
    def index(self):
        return self.candidate_indices[0] if self.automatic_read_allowed else None


def match_profile(profile, devices):
    candidates = tuple(i for i, device in enumerate(devices)
                       if profile.has_shape(InterfaceIdentity.from_mapping(device)))
    if not candidates:
        return MatchResult(profile.profile_id, MatchStatus.NO_MATCH,
                           '没有匹配的产品、接口及精确描述符')
    if len(candidates) > 1:
        return MatchResult(profile.profile_id, MatchStatus.AMBIGUOUS,
                           f'发现 {len(candidates)} 个候选接口，请明确选择物理设备', candidates)
    revision = devices[candidates[0]].get('bcd_device')
    if revision not in profile.supported_revisions:
        return MatchResult(profile.profile_id, MatchStatus.UNSUPPORTED_VERSION,
                           f'USB 设备版本 {revision or "未知"} 不在已验证范围，拒绝自动发送', candidates)
    if not profile.reviewed:
        return MatchResult(profile.profile_id, MatchStatus.CANDIDATE,
                           '档案尚未审阅，只能用于候选分析', candidates)
    return MatchResult(profile.profile_id, MatchStatus.SUPPORTED,
                       '产品、接口、USB 版本与精确描述符匹配', candidates)
