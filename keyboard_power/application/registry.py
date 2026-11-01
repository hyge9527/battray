"""Static reviewed adapters. Imported calibration JSON never enters this registry."""

from dataclasses import dataclass

from ..adapters.aula_f98pro import AulaF98ProAdapter
from ..adapters.base import BatteryAdapter
from ..domain.matching import MatchResult, MatchStatus


@dataclass(frozen=True)
class AdapterSelection:
    adapter: BatteryAdapter | None
    match: MatchResult | None


REVIEWED_ADAPTERS = (AulaF98ProAdapter(),)


def select_adapter(devices, adapters=REVIEWED_ADAPTERS):
    candidates = [(adapter, adapter.match(devices)) for adapter in adapters]
    candidates = [(adapter, match) for adapter, match in candidates if match.status is not MatchStatus.NO_MATCH]
    if not candidates:
        return AdapterSelection(None, None)
    if len(candidates) > 1:
        return AdapterSelection(None, MatchResult('', MatchStatus.AMBIGUOUS,
                                '多个适配器匹配同一目标，拒绝自动发送'))
    adapter, match = candidates[0]
    return AdapterSelection(adapter if match.automatic_read_allowed else None, match)
