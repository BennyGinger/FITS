"""Qt-independent counters shared by terminal and desktop progress displays."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from threading import RLock
from time import monotonic


@dataclass(frozen=True)
class DisplaySnapshot:
    name: str
    completed: int
    total: int
    elapsed: float
    active: bool


class DisplayProgress:
    """Retain one current batch step or conveyor bar for inexpensive polling."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._name: str | None = None
        self._completed = self._total = 0
        self._started = self._stopped = 0.0
        self._active = False

    @contextmanager
    def task(self, name: str, total: int) -> Iterator[None]:
        with self._lock:
            self._name = name
            self._completed = 0
            self._total = total
            self._started = monotonic()
            self._active = True
        try:
            yield
        finally:
            with self._lock:
                self._stopped = monotonic()
                self._active = False

    def advance(self) -> None:
        with self._lock:
            self._completed += 1

    def set_total(self, total: int) -> None:
        with self._lock:
            self._total = total

    def snapshot(self) -> DisplaySnapshot | None:
        with self._lock:
            if self._name is None:
                return None
            end = monotonic() if self._active else self._stopped
            return DisplaySnapshot(self._name, self._completed, self._total,
                                   end - self._started, self._active)
