"""Determine whether a workflow needs manual GUI input."""

from collections.abc import Mapping
from typing import Any

from fits.workflows.runtime.interactive.masks import mask_collection_requested


def interactive_inputs_requested(config: Mapping[str, Any]) -> bool:
    """
    Return whether this run needs mask collection or tracking review.
    """
    edit_tracking = config.get("edit_track", {})
    return bool(mask_collection_requested(config)
                or edit_tracking.get("enabled", False))
