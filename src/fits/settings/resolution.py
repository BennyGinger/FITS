import copy
from collections.abc import Mapping, Sequence
from typing import Any
import logging


logger = logging.getLogger(__name__)


def apply_overwrite_cascade(user_cfg: Mapping[str, Any], workflow_order: Sequence[str]) -> dict[str, Any]:
    """
    Return a copy of the configuration where overwrite propagates downstream.

    Once an enabled step requests overwrite, every later enabled step is also
    marked for overwrite so that downstream outputs are not reused from an
    older upstream result.
    """
    resolved = copy.deepcopy(dict(user_cfg))
    overwrite_downstream = False

    for step_name in workflow_order:
        step_cfg = resolved.get(step_name)

        if not isinstance(step_cfg, dict):
            continue

        if not step_cfg.get("enabled", False):
            continue

        params = step_cfg.setdefault("params", {})
        if not isinstance(params, dict):
            raise TypeError(
                f"Expected '{step_name}.params' to be a dictionary, "
                f"got {type(params).__name__}")

        step_requests_overwrite = bool(params.get("overwrite", False))

        if overwrite_downstream:
            params["overwrite"] = True
            logger.debug("Propagating overwrite from upstream to '%s'",step_name,)

        if step_requests_overwrite:
            overwrite_downstream = True

    return resolved