"""Display only files retained, renamed or removed by a compaction plan."""

from fits.environment import constant as cst
from fits.gui.file_preview.models import PreviewFile, PreviewGroup, file_title
from fits.workflows.file_management.compaction import CompactionPlan


def compaction_groups(plan: CompactionPlan) -> tuple[PreviewGroup, ...]:
    """
    Distinguish canonical final filenames from superseded files and removed caches.
    """
    groups = []
    for selection in plan.selections:
        state = selection.state
        renamed = {source for source in (selection.image, selection.mask) if source is not None}
        files = []
        targets = set()
        for source, name in ((selection.image, cst.FITS_ARRAY_NAME), (selection.mask, cst.FITS_MASKS_COMPACTED)):
            if source is None:
                continue
            target = state.workdir / name
            targets.add(target)
            detail = 'Keep the selected final pixels and revision; update compaction metadata.'
            if source != target and target.is_file():
                detail += ' The existing canonical destination will be replaced.'
            files.append(PreviewFile(target, file_title(source), 'rename' if source != target else 'keep',
                                     detail, source if source != target else None, stage=0 if source == selection.image else 1))
        preserved = {path for kind in state.artifacts if (path := state.artifact(kind)) is not None and path.is_file()}
        for template in (cst.FITS_REFERENCE_TEMPLATE, cst.FITS_ROI_TEMPLATE):
            preserved.update(state.workdir.glob(template.format(label='*')))
        for path in sorted(preserved - renamed - targets - set(plan.remove)):
            files.append(PreviewFile(path, file_title(path), 'keep', stage=-1 if path == state.original_image else 2))
        for path in plan.remove:
            if path not in renamed and path not in targets and (path.parent == state.workdir or state.workdir.name in path.parts):
                files.append(PreviewFile(path, file_title(path) if path.name in cst.MANAGED_NAMES else 'Cache',
                                         'remove', 'Removed after the retained final files are verified. Retained backups are untouched.', stage=3))
        groups.append(PreviewGroup(state.workdir, tuple(files)))
    return tuple(groups)
