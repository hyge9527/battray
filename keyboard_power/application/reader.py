"""Read one supplied inventory snapshot, with no UI or discovery side effects."""

from dataclasses import replace

from .registry import select_adapter, REVIEWED_ADAPTERS
from ..adapters.base import ReadContext
from ..adapters.system_power import read_system_power


def read_snapshot(info, context: ReadContext, adapters=REVIEWED_ADAPTERS):
    system = read_system_power(info, context)
    if system.status in ('ok', 'ambiguous_device', 'not_detected'):
        return system
    selection = select_adapter(info['devices'], adapters)
    if selection.adapter is None:
        if selection.match is None:
            return system
        reason = selection.match.reason
        if system.reading is not None:
            reason = system.reason + '；' + reason
        return replace(system, reason=reason)
    result = selection.adapter.read(info['devices'], context)
    if result.status in ('ok', 'busy'):
        return result
    if system.reading is not None:
        # Stale is still an observation; failed fallback must not erase it.
        return replace(system, checked_at=result.checked_at,
                       reason=system.reason + '；后备读取：' + result.reason)
    return result
