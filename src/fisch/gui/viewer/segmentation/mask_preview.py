"""Saved/temporary mask selection and bounded compartment preview geometry."""

from collections import OrderedDict
from pathlib import Path
from typing import Any
from collections.abc import Mapping

import numpy as np
from bioimagequant import CompartmentGeometry, prepare_compartments
from scope_io import ScopeIO
from numpy.typing import NDArray

from fisch.environment import constant as cst
from fisch.interaction.planes import PlaneStore
from fisch.settings.models import SegmentChannelSettings
from fisch.tasks.analysis.extraction.manager import resolve_extraction_labels
from fisch.tasks.segmentation.preview_cache import SegmentationPreview
from fisch.workflows.experiments import load_experiment_state


def saved_mask_path(folder: Path, *, compartment: bool, config: Mapping[str, Any] | None = None) -> Path | None:
    """
    Reuse active workflow identity, with known filenames for state-free images.
    """
    from fisch.workflows.definitions.registry import REGISTRY
    from fisch.workflows.definitions.inputs import configured_profile

    try:
        profile = configured_profile(REGISTRY[cst.StepName.EXTRACT].profile, config) if compartment and config is not None else None
    except ValueError:
        return None
    try:
        state = load_experiment_state(folder)
    except FileNotFoundError:
        names = ((cst.MASK_TRACK_EDITED_FILTERED, cst.MASK_TRACK_EDITED,
                  cst.MASK_TRACK, *cst.TRACKING_NAMES, *cst.SEGMENTATION_NAMES)
                 if compartment else cst.SEGMENTATION_NAMES)
        if profile is not None:
            if cst.ARTI_SEG in profile.additional_artifacts:
                names = cst.SEGMENTATION_NAMES
            elif not profile.use_tracking_edits:
                names = cst.UNEDITED_TRACKING_NAMES
        return next((folder / name for name in names if (folder / name).is_file()), None)
    if compartment:
        try:
            return resolve_extraction_labels(state, profile)[1]
        except ValueError:
            return None
    path = state.artifact(cst.ARTI_SEG)
    return path if path is not None and path.is_file() else None


class MaskPreviewStore:
    """
    Own temporary mask revisions and one prepared compartment distance map.
    """

    def __init__(self) -> None:
        """
        Keep preview memory bounded independently of the stack length.
        """
        self.previews: OrderedDict[tuple[int, str, int], tuple[SegmentChannelSettings, SegmentationPreview]] = OrderedDict()
        self._reader: ScopeIO | None = None
        self._planes: PlaneStore | None = None
        self._file_revision: tuple[Path, int, int] | None = None
        self._geometry_key: tuple[Any, ...] | None = None
        self._geometry: CompartmentGeometry | None = None
        self._saved_settings: dict[tuple[Path, str], tuple[tuple[Any, ...], SegmentChannelSettings]] = {}

    def remember(self, preview: SegmentationPreview, settings: SegmentChannelSettings, z: int) -> None:
        """
        Remember the result revision and settings that actually produced its mask.
        """
        key = (preview.frame_index, settings.channel, z)
        self.previews[key] = (settings.model_copy(deep=True), preview)
        self.previews.move_to_end(key)
        while len(self.previews) > 8:
            self.previews.popitem(last=False)

    def channels(self, source: Path | None) -> tuple[str, ...]:
        """
        Return saved mask channels without loading the complete mask stack.
        """
        self._open(source)
        return tuple(self._reader.channel_labels) if self._reader is not None else ()

    def mask(self, source: Path | None,
             frame: int,
             channel: str,
             z: int,
             settings: SegmentChannelSettings,
             ) -> tuple[NDArray[Any], tuple[Any, ...], str, bool] | None:
        """
        Prefer a temporary preview, marking it stale when its settings changed.
        """
        item = self.previews.get((frame, channel, z))
        if item is not None:
            produced, preview = item
            mask = preview.mask
            if "Z" in preview.mask_axes:
                mask = np.max(mask, axis=preview.mask_axes.index("Z"))
            stamp = preview.cache_path.stat().st_mtime_ns if preview.cache_path.exists() else id(preview)
            return mask, (preview.cache_path, stamp, frame, channel, z), "Segmentation preview", produced != settings
        self._open(source)
        if source is None or self._reader is None or self._planes is None or channel not in self._reader.channel_labels:
            return None
        index = list(self._reader.channel_labels).index(channel)
        revision = (self._file_revision, self._reader.reader.metadata.artifact.created_at)
        identity = (source, channel)
        previous = self._saved_settings.get(identity)
        if previous is None or previous[0] != revision:
            self._saved_settings[identity] = (revision, settings.model_copy(deep=True))
        stale = self._saved_settings[identity][1] != settings
        return (self._planes.plane(frame, index, z),
                (*revision, frame, channel, z),
                f"Saved mask: {source.name}", stale)

    def membrane(self, mask: NDArray[Any], revision: tuple[Any, ...], thickness: float, dilation: float) -> NDArray[Any]:
        """
        Reuse distances for thickness changes, rebuilding only for a new mask/dilation.
        """
        key = (*revision, dilation)
        if key != self._geometry_key:
            self._geometry = prepare_compartments(mask, dilation)
            self._geometry_key = key
        assert self._geometry is not None
        return self._geometry.masks(thickness)["mb"]

    def _open(self, source: Path | None) -> None:
        """
        Refresh saved data when its source revision changes.
        """
        revision = (source, source.stat().st_size, source.stat().st_mtime_ns) if source is not None else None
        if revision == self._file_revision:
            return
        if self._planes is not None:
            self._planes.close()
        self._file_revision = revision
        self._reader = ScopeIO.from_path(source) if source is not None else None
        self._planes = (PlaneStore(self._reader.axes, tuple(self._reader.reader.shape), reader=self._reader)
                        if self._reader is not None else None)

    def close(self) -> None:
        """
        Release saved plane caches and all temporary geometry references.
        """
        if self._planes is not None:
            self._planes.close()
        self._reader = None
        self._planes = None
        self._file_revision = None
        self.previews.clear()
        self._saved_settings.clear()
        self._geometry = None
        self._geometry_key = None
