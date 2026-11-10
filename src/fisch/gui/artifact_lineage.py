"""File-level impact diagrams built from the existing preflight inventory."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from PySide6.QtWidgets import QWidget
from fisch.gui.file_preview.models import Action, PreviewFile, PreviewGroup, STEP_ORDER as _STEP_ORDER, file_title
from fisch.gui.file_preview.widget import FilePreviewWidget

from fisch.environment import constant as cst
from fisch.workflows.artifacts.branch_masks import geometry, is_branch
from fisch.workflows.checks.models import ArtifactRecord, PreflightReport


Role = Literal["input", "selected", "affected", "conflict", "planned"]
_CAPTIONS: dict[Role, str] = {
    "input": "Input / unchanged",
    "selected": "Rerun / overwrite",
    "affected": "Affected downstream",
    "conflict": "Existing conflict",
    "planned": "Included if rebuilding",
}
_ACTIONS: dict[Role, Action] = {'input': 'keep', 'selected': 'rebuild', 'affected': 'affected',
                               'conflict': 'conflict', 'planned': 'rebuild'}


@dataclass(frozen=True)
class LineageNode:
    """Describe one displayed file and its preflight impact category."""

    path: Path
    step: str | None
    role: Role
    problem: str = ""
    new_output: bool = False
    legacy: bool = False


@dataclass(frozen=True)
class FileLineage:
    """Keep recorded file relationships separate from planned rebuild outputs."""

    nodes: tuple[LineageNode, ...]
    edges: tuple[tuple[Path, Path], ...]
    geometry_edges: tuple[tuple[Path, Path], ...] = ()


def _registration_will_change(report: PreflightReport, directory: Path) -> bool:
    """
    Identify registration stages included in this experiment's possible rerun.
    """
    registration = {cst.StepName.REGISTER_CHANNEL, cst.StepName.REGISTER_TIME}
    present = {record.step for record in report.records if record.path.resolve().parent == directory}
    planned = {step for step, path in report.rebuild_outputs if path.resolve().parent == directory}
    return bool(registration & (planned | (present & (set(report.overwritten) | set(report.affected)))))


def _geometry_input(record: ArtifactRecord, records: dict[Path, ArtifactRecord]) -> Path | None:
    """
    Attach manual drawings to image geometry rather than intensity processing.
    """
    stages = {cst.StepName.CONVERT, cst.StepName.REGISTER_CHANNEL, cst.StepName.REGISTER_TIME}
    candidates = [candidate for candidate in records.values()
                  if candidate.path.resolve().parent == record.path.resolve().parent and candidate.step in stages]
    if not candidates:
        candidates = [candidate for candidate in records.values()
                      if candidate.path.resolve().parent == record.path.resolve().parent
                      and candidate.path.name == cst.ARRAY_NAME]
    if record.metadata is not None:
        matching = [candidate for candidate in candidates if candidate.metadata is not None
                    and geometry(candidate.metadata) == geometry(record.metadata)]
        if matching:
            candidates = matching
    if not candidates:
        return None
    source = max(candidates, key=lambda candidate: _STEP_ORDER.get(candidate.step or "", -1))
    return source.path.resolve()


def _record_node(record: ArtifactRecord, report: PreflightReport, planned: set[Path]) -> LineageNode:
    """
    Assign impact from the report without inventing additional downstream work.
    """
    path = record.path.resolve()
    role: Role = "input"
    if record.legacy:
        role = "conflict"
    elif is_branch(path):
        if record.problem:
            role = "conflict"
        elif _registration_will_change(report, path.parent):
            role = "affected"
    elif record.step in report.overwritten:
        role = "selected"
    elif record.step in report.affected:
        role = "affected"
    elif record.problem:
        role = "conflict"
    elif path in planned:
        role = "planned"
    return LineageNode(path, record.step, role, record.problem, legacy=record.legacy)


def file_lineage(report: PreflightReport, directory: Path) -> FileLineage:
    """
    Collect one experiment's files, actual recorded ancestors and rebuild outputs.
    """
    directory = directory.resolve()
    records = {record.path.resolve(): record for record in report.records}
    planned = {path.resolve() for _, path in report.rebuild_outputs}
    pending = [record for path, record in records.items() if path.parent == directory]
    nodes = {record.path.resolve(): _record_node(record, report, planned) for record in pending}
    edges: set[tuple[Path, Path]] = set()
    geometry_edges: set[tuple[Path, Path]] = set()
    visited: set[Path] = set()
    while pending:
        record = pending.pop()
        target = record.path.resolve()
        if target in visited:
            continue
        visited.add(target)
        if is_branch(record.path):
            source = _geometry_input(record, records)
            if source is not None:
                geometry_edges.add((source, target))
                if source not in nodes:
                    nodes[source] = _record_node(records[source], report, planned)
                    pending.append(records[source])
            continue
        refs = record.metadata.artifact.derived_from if record.metadata is not None else None
        if not isinstance(refs, list):
            continue
        for ref in refs:
            relative = ref.get("artifact_path")
            if not isinstance(relative, str):
                continue
            source = (record.path.parent / relative).resolve()
            if source == target:
                continue
            edges.add((source, target))
            if source not in nodes:
                ancestor = records.get(source)
                nodes[source] = (_record_node(ancestor, report, planned) if ancestor is not None
                                 else LineageNode(source, None, "input"))
                if ancestor is not None:
                    pending.append(ancestor)
    for step, output in report.rebuild_outputs:
        path = output.resolve()
        if path.parent == directory and path not in nodes:
            role: Role = "affected" if step in report.affected else "planned"
            nodes[path] = LineageNode(path, step, role, new_output=True)
    return FileLineage(tuple(nodes.values()), tuple(sorted(edges)), tuple(sorted(geometry_edges)))


def _node_caption(node: LineageNode) -> str:
    """
    Distinguish preserved older files and prospective outputs from current overwrites.
    """
    if node.legacy:
        return "Earlier-version result (preserved)"
    if node.new_output:
        return "New output if rebuilding"
    if is_branch(node.path):
        return "Review after registration" if node.role == "affected" else (
            "Geometry needs review" if node.role == "conflict" else "Unchanged / geometry only")
    return _CAPTIONS[node.role]


def _preview_group(report: PreflightReport, directory: Path) -> PreviewGroup:
    """
    Adapt recorded conflict relationships to the shared file-icon presentation.
    """
    graph = file_lineage(report, directory)
    files = []
    for node in graph.nodes:
        action: Action = ('keep' if node.legacy else 'create' if node.new_output else
                          'review' if is_branch(node.path) and node.role == 'affected' else
                          _ACTIONS[node.role])
        step = str(cst.StepName.EXTRACT) if node.step == cst.StepName.DISTANCE_PROFILE else node.step
        files.append(PreviewFile(node.path, file_title(node.path, node.step), action,
                                 _node_caption(node) + ('\n' + node.problem if node.problem else ''),
                                 stage=_STEP_ORDER.get(step or '', -1), branch=is_branch(node.path)))
    return PreviewGroup(directory, tuple(files), graph.edges, graph.geometry_edges)


class ArtifactLineageWidget(FilePreviewWidget):
    """
    Show conflict-review semantics using the same icons as other file-action reviews.
    """

    def __init__(self, report: PreflightReport, parent: QWidget | None = None, *, compact: bool = False) -> None:
        """
        Preserve saved dependencies, conditional rebuilds and manual-mask review warnings.
        """
        directories = {record.path.resolve().parent for record in report.records}
        directories.update(path.resolve().parent for _, path in report.rebuild_outputs)
        groups = tuple(_preview_group(report, directory) for directory in sorted(directories))
        if report.legacy:
            guidance = 'Earlier-version results are preserved. Rebuilding creates current-version results from the original acquisitions.'
        elif compact:
            guidance = 'Affected results are updated only if you choose rebuild before compacting; choosing keep retains them.'
        elif report.overwritten:
            guidance = ('Selected files will be overwritten. Affected downstream files are rebuilt only with '
                        '“Selected step and downstream”; “Selected step only” keeps them and can leave conflicts.')
        else:
            guidance = 'Highlighted files have conflicts or are included in the rebuild plan. Continuing without rebuilding retains existing results.'
        super().__init__(groups, guidance, parent)
