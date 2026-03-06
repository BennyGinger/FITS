from __future__ import annotations

import json
import logging
import threading
from typing import Any

from cellpose_kit.client import CellposeWrapper


logger = logging.getLogger(__name__)


class SegmentModelCache:
    def __init__(self) -> None:
        self._cache: dict[str, CellposeWrapper] = {}
        self._lock = threading.Lock()

    def get_wrapper(self, segment_settings: dict) -> CellposeWrapper:
        model_settings = self._extract_model_settings(segment_settings)
        key = self._make_key(model_settings)

        cached = self._cache.get(key)
        if cached is not None:
            logger.debug("Reusing cached CellposeWrapper for key=%s", key)
            return cached

        with self._lock:
            cached = self._cache.get(key)
            if cached is not None:
                logger.debug("Reusing cached CellposeWrapper for key=%s", key)
                return cached

            logger.info("Creating new cached CellposeWrapper for key=%s", key)
            wrapper = CellposeWrapper.from_dict(segment_settings)
            wrapper.setup()
            self._cache[key] = wrapper
            return wrapper

    def _extract_model_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        model_settings: dict[str, Any] = {}

        for key in ("threading", "use_nuclear_channel", "do_denoise", "model"):
            if key in settings:
                model_settings[key] = settings[key]

        user_settings = settings.get("user_settings", {})
        if isinstance(user_settings, dict):
            model_settings["user_settings"] = user_settings
        else:
            model_settings["user_settings"] = {}

        return model_settings

    def _make_key(self, model_settings: dict[str, Any]) -> str:
        return json.dumps(model_settings, sort_keys=True, default=str)

    def clear_cache(self) -> None:
        with self._lock:
            self._cache.clear()
        logger.info("Segment model cache cleared")


segment_model_cache = SegmentModelCache()
