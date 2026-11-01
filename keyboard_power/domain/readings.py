from dataclasses import dataclass
import math


@dataclass(frozen=True)
class Reading:
    percent: int | float
    source: str | None
    observed_at: int | float | None
    received_at: int | float | None
    fresh: bool = True
    received_monotonic: float | None = None

    def __post_init__(self):
        if type(self.percent) not in (int, float) or not math.isfinite(self.percent) or not 0 <= self.percent <= 100:
            raise ValueError('percentage must be finite and in 0..100')
        for value in (self.observed_at, self.received_at, self.received_monotonic):
            if value is not None and (type(value) not in (int, float) or not math.isfinite(value)):
                raise ValueError('reading timestamps must be finite or unknown')

    @classmethod
    def from_legacy(cls, result):
        if result.get('percent') is None:
            return None
        return cls(result['percent'], result.get('source'), result.get('updated_at'),
                   result.get('checked_at'), result.get('status') == 'ok')

    def expired(self, now_monotonic, ttl):
        if not self.fresh:
            return True
        if ttl < 0:
            raise ValueError('ttl cannot be negative')
        return self.received_monotonic is not None and now_monotonic - self.received_monotonic > ttl


@dataclass(frozen=True)
class ReadAttempt:
    connection_id: str
    generation: int
    sequence: int
    status: str
    reason: str
    checked_at: int | float | None
    reading: Reading | None = None

    def __post_init__(self):
        if type(self.sequence) is not int or self.sequence < 0:
            raise ValueError('attempt sequence must be a nonnegative integer')
