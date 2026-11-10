"""Public orchestration for static tracked-mask processing."""

import numpy as np
from numpy.typing import NDArray

from fisch.tasks.tracking.static_masks.completion import complete_tracks
from fisch.tasks.tracking.static_masks.filtering import filter_tracks
from fisch.tasks.tracking.static_masks.identities import build_temporal_supermask, reconnect_identities
from fisch.tasks.tracking.static_masks.validation import validate_masks, validate_parameters


def process_static_masks(masks: NDArray[np.generic],
                         *,
                         shape_similarity: float = 0.9,
                         minimum_appearances: int = 5,
                         extrapolate_start: bool = True,
                         extrapolate_end: bool = True,
                         ) -> NDArray[np.generic]:
    """
    Clean and complete a ``TYX`` static-cell mask movie using trustworthy anchors.

    Reconnection and collision clipping use the IoU equivalent of the requested
    Dice consistency, with the legacy 0.5 minimum overlap as a lower bound.
    """
    validate_masks(masks)
    validate_parameters(shape_similarity=shape_similarity,
                        minimum_appearances=minimum_appearances,)

    supermask = build_temporal_supermask(masks)
    minimum_iou = max(0.5, shape_similarity / (2 - shape_similarity))
    reconnected = reconnect_identities(masks, supermask, minimum_iou=minimum_iou)
    filtered = filter_tracks(reconnected,
                             shape_similarity=shape_similarity,
                             minimum_appearances=minimum_appearances,)
    return complete_tracks(filtered,
                           extrapolate_start=extrapolate_start,
                           extrapolate_end=extrapolate_end,
                           minimum_iou=minimum_iou,
                           )
