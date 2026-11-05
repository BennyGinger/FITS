"""Combine experiment previews into one temporary whole-run stage schematic."""

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from fits.gui.file_preview.models import Action, PreviewFile, PreviewGroup, file_title, workflow_sequence

LinkKind = Literal['saved', 'planned', 'geometry', 'sequence']
_COUNT_LABELS: dict[Action, str] = {
    'keep': 'kept', 'create': 'new', 'rebuild': 'rebuilt', 'affected': 'affected',
    'rename': 'renamed', 'move': 'moved', 'remove': 'removed', 'review': 'for review',
    'conflict': 'with conflicts', 'update': 'updated', 'regenerate': 'regenerated',
}
_IMPACT: dict[Action, int] = {'keep': 0, 'conflict': 1, 'create': 2, 'move': 3, 'rename': 3,
                            'update': 3, 'review': 3, 'regenerate': 4, 'affected': 4,
                            'rebuild': 4, 'remove': 5}


def _identity(item: PreviewFile) -> tuple[int, str, bool]:
    """
    Group full-mask variants with their ordinary tracking/segmentation stage.
    """
    title = file_title(item.path) if item.title.endswith(' (full)') else item.title
    return item.stage, title, item.branch


def _key(identity: tuple[int, str, bool]) -> str:
    """
    Give scene items a stable stage identifier independent of individual filenames.
    """
    stage, title, branch = identity
    return f'{stage}:{int(branch)}:{title}'


@dataclass(frozen=True)
class OverviewStage:
    """
    Represent unique physical files at a workflow stage across the reviewed run.
    """

    key: str
    title: str
    stage: int
    branch: bool
    files: tuple[PreviewFile, ...]

    @property
    def file_count(self) -> str:
        """
        Format the unique file count for stage icons, tooltips and detail headings.
        """
        return f'{len(self.files)} ' + ('file' if len(self.files) == 1 else 'files')

    @property
    def action(self) -> Action:
        """
        Keep overwrites purple, downstream changes orange and entirely new stages blue.
        """
        if all(item.action == 'create' for item in self.files):
            return 'create'
        if all(item.action == 'keep' for item in self.files):
            return 'keep'
        if any(item.action == 'rebuild' for item in self.files):
            return 'rebuild'
        return 'update'

    @property
    def count_summary(self) -> str:
        """
        Keep per-action counts explicit so orange never implies every file changes.
        """
        counts = Counter(item.action for item in self.files)
        return ' · '.join(f'{counts[action]} {_COUNT_LABELS[action]}' for action in _COUNT_LABELS if counts[action])

    @property
    def renames(self) -> tuple[tuple[str, str, int], ...]:
        """
        Retain shared rename patterns even when other files already have the target name.
        """
        counts = Counter((item.source.name, item.path.name) for item in self.files
                         if item.source is not None and item.source.name != item.path.name)
        return tuple((old, new, count) for (old, new), count in sorted(counts.items()))


@dataclass(frozen=True)
class OverviewLink:
    """
    Keep workflow order distinct from recorded, proposed and geometry relationships.
    """

    source: str
    target: str
    kind: LinkKind


@dataclass(frozen=True)
class RunOverview:
    """
    Store the stage-level presentation without changing the executable plans.
    """

    stages: tuple[OverviewStage, ...]
    links: tuple[OverviewLink, ...]


def _collect_stages(groups: tuple[PreviewGroup, ...]) -> tuple[OverviewStage, ...]:
    """
    Deduplicate shared originals and prefer the strongest action for a repeated file.
    """
    stages: dict[tuple[int, str, bool], dict[Path, PreviewFile]] = {}
    for group in groups:
        for item in group.files:
            files = stages.setdefault(_identity(item), {})
            previous = files.get(item.path)
            if previous is None or _IMPACT[item.action] > _IMPACT[previous.action]:
                files[item.path] = item
    result = []
    for identity, files in sorted(stages.items()):
        stage, title, branch = identity
        if any(item.title.endswith(' (full)') for item in files.values()):
            title += ' (full)'
        result.append(OverviewStage(_key(identity), title, stage, branch,
                                     tuple(files[path] for path in sorted(files))))
    return tuple(result)


def _collect_links(groups: tuple[PreviewGroup, ...]) -> tuple[OverviewLink, ...]:
    """
    Merge actual per-experiment relationships without connecting unrelated analyses.
    """
    links: dict[tuple[str, str], LinkKind] = {}
    for group in groups:
        keys = {item.path: _key(_identity(item)) for item in group.files}
        categories: tuple[tuple[tuple[tuple[Path, Path], ...], LinkKind], ...] = (
            (group.edges, 'planned' if group.planned_edges else 'saved'),
            (workflow_sequence(group.files), 'sequence'), (group.geometry_edges, 'geometry'))
        for edges, kind in categories:
            for source, target in edges:
                first, second = keys.get(source), keys.get(target)
                if first is not None and second is not None and first != second:
                    pair = first, second
                    if pair not in links or kind in ('sequence', 'geometry'):
                        links[pair] = kind
    return tuple(OverviewLink(source, target, kind) for (source, target), kind in sorted(links.items()))


def run_overview(groups: tuple[PreviewGroup, ...]) -> RunOverview:
    """
    Build a whole-run schematic from the same per-file plans used for execution.
    """
    return RunOverview(_collect_stages(groups), _collect_links(groups))
