"""Backend contracts; no GUI, settings, enumeration or scheduling ownership."""

from dataclasses import dataclass
import time
from typing import Callable, Protocol

from ..domain.matching import DeviceProfile, MatchResult
from ..domain.readings import Reading


@dataclass(frozen=True)
class ReadContext:
    cancel_fd: int | None = None
    trace: Callable | None = None
    clock: Callable = time.time


@dataclass(frozen=True)
class BackendResult:
    status: str
    reason: str
    checked_at: int | float
    device: str = '无线键盘'
    reading: Reading | None = None

    def to_legacy(self):
        """Keep the public CLI/IPC dictionary stable during service migration."""
        reading = self.reading
        return dict(device=self.device, percent=reading.percent if reading else None,
                    source=reading.source if reading else None,
                    updated_at=reading.observed_at if reading else None,
                    checked_at=self.checked_at, status=self.status, reason=self.reason)


class BatteryAdapter(Protocol):
    """Reviewed vendor backend contract used by the static registry."""

    profile: DeviceProfile

    def match(self, devices) -> MatchResult: ...

    def read(self, devices, context: ReadContext) -> BackendResult: ...
