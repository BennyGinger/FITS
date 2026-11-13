"""Temporary presentation data derived from reviewed file-management plans."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from fisch.environment import constant as cst

Action = Literal['keep', 'create', 'rebuild', 'affected', 'rename', 'move', 'remove', 'review', 'conflict', 'update', 'regenerate']
CAPTIONS: dict[Action, str] = {
    'keep': 'Kept', 'create': 'Will be created', 'rebuild': 'Will be rebuilt',
    'affected': 'Rebuilt if selected', 'rename': 'Will be renamed', 'move': 'Will be moved',
    'remove': 'Will be removed', 'review': 'Alignment review', 'conflict': 'Existing conflict',
    'update': 'Metadata updated', 'regenerate': 'Will be regenerated',
}
CURRENT_COLOR = '#7dbbb0'
CHANGED_COLOR = '#f2ac5b'
CREATED_COLOR = '#80bfff'
OVERWRITE_COLOR = '#c49bff'
COLORS: dict[Action, str] = dict.fromkeys(CAPTIONS, CHANGED_COLOR)
COLORS.update({'keep': CURRENT_COLOR, 'create': CREATED_COLOR, 'rebuild': OVERWRITE_COLOR})
STEP_TITLES: dict[str, str] = {
    cst.StepName.CONVERT: 'Converted', cst.StepName.REGISTER_CHANNEL: 'Channel-shifted',
    cst.StepName.REGISTER_TIME: 'Frame-shifted', cst.StepName.BG_SUB: 'Background-subtracted',
    cst.StepName.SEGMENT: 'Segmented', cst.StepName.TRACK: 'Tracked',
    cst.StepName.EDIT_TRACK: 'Edited tracks', cst.StepName.EXTRACT: 'Measurements',
    cst.StepName.DISTANCE_PROFILE: 'Distance profile',
}
STEP_ORDER = {str(step): index for index, step in enumerate(cst.WORKFLOW_ORDER)}


_IMAGE_STEPS = cst.IMAGE_STEPS
_FILE_STEPS: dict[str, str] = dict(zip(cst.IMAGE_STAGE_NAMES, _IMAGE_STEPS, strict=True))
_FILE_STEPS.update({name: cst.StepName.SEGMENT for name in cst.SEGMENTATION_NAMES})
_FILE_STEPS.update({name: cst.StepName.TRACK for name in cst.TRACKING_NAMES})
_FILE_STEPS.update({cst.MASK_TRACK_EDITED: cst.StepName.EDIT_TRACK,
                    cst.MASK_TRACK_EDITED_FILTERED: cst.StepName.EDIT_TRACK,
                    cst.QUANTI_NAME: cst.StepName.EXTRACT,
                    cst.DISTANCE_PROFILE_NAME: cst.StepName.DISTANCE_PROFILE})
_FILE_TITLES = {name: STEP_TITLES[step] for name, step in _FILE_STEPS.items()}
_FILE_TITLES.update({cst.MASKS_COMPACTED: 'Final masks', cst.ARRAY_NAME: 'Final image'})


def file_stage(path: Path, step: str | None = None) -> int:
    """
    Order known files by workflow stage and keep independent analyses parallel.
    """
    step = _FILE_STEPS.get(path.name, step)
    if path.name in cst.COMPARTMENT_MASK_NAMES:
        step = cst.StepName.EXTRACT
    return STEP_ORDER.get(str(cst.StepName.EXTRACT) if step == cst.StepName.DISTANCE_PROFILE else step or '', -1)


@dataclass(frozen=True)
class PreviewFile:
    """
    Describe a destination file and its planned action without changing workflow state.
    """

    path: Path
    title: str
    action: Action = 'keep'
    detail: str = ''
    source: Path | None = None
    stage: int = -1
    branch: bool = False


@dataclass(frozen=True)
class PreviewGroup:
    """
    Show one destination folder and its saved or explicitly planned relationships.
    """

    directory: Path
    files: tuple[PreviewFile, ...]
    edges: tuple[tuple[Path, Path], ...] = ()
    geometry_edges: tuple[tuple[Path, Path], ...] = ()
    planned_edges: bool = False


def file_order(item: PreviewFile) -> tuple[int, str]:
    """
    Keep active or proposed outputs above preserved or superseded versions.
    """
    rank = 2 if item.action == 'remove' else 1 if item.action in ('keep', 'conflict') else 0
    return rank, str(item.path)


def workflow_sequence(files: tuple[PreviewFile, ...]) -> tuple[tuple[Path, Path], ...]:
    """
    Link successive workflow stages without treating display order as recorded provenance.
    """
    stages: dict[int, list[PreviewFile]] = {}
    for item in files:
        if not item.branch and item.action != 'remove':
            stages.setdefault(item.stage, []).append(item)
    ordered: list[list[PreviewFile]] = []
    for stage in sorted(stages):
        items = stages[stage]
        rank = min(file_order(item)[0] for item in items)
        ordered.append([item for item in items if file_order(item)[0] == rank])
    return tuple((source.path, target.path) for before, after in zip(ordered, ordered[1:])
                 for source in before for target in after)


def file_summary(item: PreviewFile) -> str:
    """
    Describe a selected file in one short line; keep full paths in the tooltip.
    """
    name = item.path.name
    if item.source is not None and item.source.name != name:
        name = f'{item.source.name} → {name}'
    summary = f'{name} — {CAPTIONS[item.action]}'
    if item.action == 'conflict' and item.detail:
        summary += ': ' + item.detail.splitlines()[-1]
    return summary


@dataclass(frozen=True)
class FileChange:
    """
    Explain a modified file, optionally showing its previous location.
    """

    path: Path
    action: str
    detail: str
    source: Path | None = None


def file_title(path: Path, step: str | None = None) -> str:
    """
    Name known artifact roles using the central filenames and workflow definitions.
    """
    if path.name in cst.COMPARTMENT_MASK_NAMES:
        return 'Cytoplasm (_cyto)' if path.stem.endswith('_cyto') else 'Membrane (_mb)'
    if path.match(cst.REFERENCE_TEMPLATE.format(label='*')):
        return 'Reference'
    if path.match(cst.ROI_TEMPLATE.format(label='*')):
        return 'ROI'
    return _FILE_TITLES.get(path.name, STEP_TITLES.get(step or '', 'Original' if path.suffix.lower() != '.parquet' else 'Measurements'))
