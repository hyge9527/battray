"""Pure result ordering. UI, clocks and hardware access are outside this module."""

from dataclasses import dataclass, replace

from .identity import Connection
from .readings import Reading, ReadAttempt


@dataclass(frozen=True)
class DeviceState:
    connection: Connection
    reading: Reading | None = None
    attempt: ReadAttempt | None = None

    @property
    def status(self):
        if self.attempt is None:
            return 'unknown'
        if self.reading is None:
            return self.attempt.status
        return 'ok' if self.attempt.status == 'ok' and self.reading.fresh else 'stale'


def choose_reading(current, incoming):
    if incoming is None:
        return current
    if current is None:
        return incoming
    if current.observed_at is not None and incoming.observed_at is not None:
        if incoming.observed_at != current.observed_at:
            return incoming if incoming.observed_at > current.observed_at else current
    # Never invent a sampling time when either provider does not supply one.
    if current.fresh != incoming.fresh:
        return incoming if incoming.fresh else current
    return incoming


def reduce_attempt(state, attempt):
    connection = state.connection
    if (attempt.connection_id, attempt.generation) != (connection.connection_id, connection.generation):
        return state
    if state.attempt is not None and attempt.sequence <= state.attempt.sequence:
        return state
    return replace(state, reading=choose_reading(state.reading, attempt.reading), attempt=attempt)
