"""Immutable result of a run-wide channel-label inspection."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LabelPlan:
    run_dir: Path
    labels: tuple[tuple[int, str], ...]
    tiffs: tuple[Path, ...]
    tables: tuple[Path, ...]
    settings: tuple[Path, ...]
    states: tuple[Path, ...]
    file_labels: tuple[tuple[Path, frozenset[str]], ...]
    fingerprints: tuple[tuple[Path, tuple[int, int]], ...]

    @property
    def files(self) -> tuple[Path, ...]:
        return self.tiffs + self.tables + self.settings + self.states


