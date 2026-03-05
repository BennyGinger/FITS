from __future__ import annotations
from collections.abc import Sequence
from dataclasses import dataclass, replace, field
import json
import logging
import os
from pathlib import Path
import tempfile
from typing import Any, Literal
from datetime import datetime

from fits.environment.constant import FITS_ARRAY_NAME, FitsName, FITS_MASK_NAME
from fits.environment.serialization import deserialize_experiment_state, serialize_experiment_state
from fits.workflows.tasks.metadata import OutputStateMeta


OutputKey = Literal["image", "masks"]
VALID_OUTPUT_KEYS: set[OutputKey] = {"image", "masks"}
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExperimentState():
    """
    Main wrapper for experiment state information during pipeline execution.
    
    Attributes:
        run_dir: Base directory for the current run, used for resolving relative paths and storing outputs.
        original_image: Path to the original image file.
        image: Optional Path to the FITS experiment image.
        masks: Optional Path to the FITS experiment masks.
        last_step: Optional name of the last completed step in the pipeline, used for resuming or tracking progress.
        experiment_id: Stable identifier for this experiment instance, including series.
        series_index: Index of the series (for multi-series experiments).
        step_status: Dictionary tracking status of each step (pending/running/done/failed/skipped).
        step_settings_hash: Dictionary storing hash of settings used for each step.
        last_error: Error message from the last failed step.
        updated_at: Timestamp of last state update.
    """
    
    run_dir: Path
    original_image_rel: Path
    image_rel: Path | None = None
    masks_rel: Path | None = None
    last_step: str | None = None
    experiment_id: str | None = None
    series_index: int = 0
    step_meta: dict[str, Any] = field(default_factory=dict)
    last_error: str | None = None
    updated_at: datetime | None = None
    
    @classmethod
    def init(cls, run_dir: Path, original_image: Path) -> ExperimentState:
        """
        Initialize a new ExperimentState with the given run directory and original image path.
        
        Args:
            run_dir: Base directory for the current run.
            original_image: Path to the original image file. This will be stored as a relative path to run_dir in the state.
            
        Returns:
            An initialized ExperimentState instance with relative paths set.
        """
        return cls(
            run_dir=run_dir,
            original_image_rel=cls._to_relative(run_dir, original_image),
            updated_at=datetime.now()
        )
        
    def with_image(self, image_path: Path, **kwargs) -> ExperimentState:
        """
        Return a new ExperimentState with the image path set.
        """
        img_rel = self._to_relative(self.run_dir, image_path)
        exp_id = img_rel.parent.as_posix()
        
        # Try to extract series index from folder name (e.g., "exp1_s0" -> 0)
        series = self.series_index  # default to existing value
        parts = img_rel.parent.name.rsplit("_s", 1)
        if len(parts) == 2 and parts[1]:
            try:
                series = int(parts[1])
            except ValueError:
                pass
        
        return replace(self, image_rel=img_rel, experiment_id=exp_id, series_index=series, updated_at=datetime.now(), **kwargs)
    
    def with_masks(self, masks_path: Path, **kwargs) -> ExperimentState:
        """
        Return a new ExperimentState with the masks path set.
        """
        return replace(self, masks_rel=self._to_relative(self.run_dir, masks_path), updated_at=datetime.now(),**kwargs)
    
    def to_json(self) -> ExperimentState:
        """
        Serialize the experiment state to ``workdir/experiment_state.json``.
        """
        if self.workdir is None:
            raise ValueError("workdir is not available; set image before calling to_json().")
        target_path = self.workdir / "experiment_state.json"
        target_path.parent.mkdir(parents=True, exist_ok=True)

        payload = json.dumps(serialize_experiment_state(self), indent=2, sort_keys=True)
        fd, temp_path_str = tempfile.mkstemp(
            dir=target_path.parent,
            prefix=f".{target_path.name}.",
            suffix=".tmp",
            text=True,
        )
        temp_path = Path(temp_path_str)

        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, target_path)
        except Exception:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise

        return self

    @classmethod
    def from_json(cls, workdir: Path) -> ExperimentState:
        """
        Load an experiment state from ``workdir/experiment_state.json``.
        """
        json_path = workdir / "experiment_state.json"
        raw = json.loads(json_path.read_text(encoding="utf-8"))
        return cls(**deserialize_experiment_state(raw))
    
    @property
    def workdir(self) -> Path | None:
        """
        Get the working directory for the experiment, which is the parent directory of the FITS array.
        """
        return self.image.parent if self.image is not None and isinstance(self.image, Path) else None
    
    @property
    def original_image(self) -> Path:
        """
        Get the absolute path to the original image by resolving the relative path against run_dir.
        """
        return self._to_absolute(self.original_image_rel)
    
    @property
    def image(self) -> Path | None:
        """
        Get the absolute path to the FITS image, or None if not set.
        """
        return self._to_absolute(self.image_rel) if self.image_rel is not None else None
    
    @property
    def masks(self) -> Path | None:
        """
        Get the absolute path to the FITS masks, or None if not set.
        """
        return self._to_absolute(self.masks_rel) if self.masks_rel is not None else None
    
    @staticmethod
    def _to_relative(base_dir: Path, path: Path) -> Path:
        """
        Convert an absolute path to be relative to run_dir.
        
        If path is already relative returns it as-is. If path is absolute but not under run_dir, raises ValueError.
        
        Args:
            base_dir: Base directory to which the path should be made relative.
            path: Path to convert.
            
        Returns:
            Path relative to run_dir, or original path if conversion not possible.
        """
        if path.is_absolute():
            try:
                return path.relative_to(base_dir)
            except ValueError:
                raise ValueError(f"{path} is not under run_dir {base_dir}")
        return path
    
    def _to_absolute(self, path: Path) -> Path:
        """
        Convert a path to be absolute relative to run_dir.
        
        If path is already absolute, returns it as-is.
        
        Args:
            path: Path to convert (relative to run_dir or already absolute).
            
        Returns:
            Absolute path resolved from run_dir, or original if already absolute.
        """
        if not path.is_absolute():
            return self.run_dir / path
        return path
    
    def _exists(self, p: Path | None) -> bool:
        return p is not None and p.exists()

    def needs_run(self, step: str, settings_hash: str, required_channel: Sequence[str] | None, overwrite: bool, required_output: FitsName) -> bool:
        """
        Returns True if:
        - overwrite is True, or
        - any of the required channels for the step are not marked as "done" in the step_meta, or their settings hash does not match the provided settings_hash, or
        - the required primary output (FITS_ARRAY_NAME or FITS_MASK_NAME) does not exist at the expected location.
        """
        # overwrite gate
        if overwrite:
            return True
        
        # status/setting gate
        step_meta = self.step_meta.get(step, {})
        chan_meta = step_meta.get("channels", {})
        
        required_channel = required_channel or []
        for label in required_channel:
            label_meta = chan_meta.get(label, {})
            if label_meta.get("status") != "done":
                return True
            if label_meta.get("hashed_settings") != settings_hash:
                return True
        
        # required primary outputs
        if required_output == FITS_ARRAY_NAME and not self._exists(self.image):
            return True
        if required_output == FITS_MASK_NAME and not self._exists(self.masks):
            return True

        return False
    
    def with_update(self, output_meta: OutputStateMeta) -> ExperimentState:
        """
        Return a new ExperimentState with updated paths and metadata based on the provided OutputStateMeta.
        """
        if output_meta.mark_failed and output_meta.mark_done:
            raise ValueError("OutputStateMeta cannot be both failed and done")
        
        st = self
        output_path = None
        if output_meta.with_image is not None:
            st = st.with_image(output_meta.with_image, last_step=output_meta.step)
            output_path = st.image_rel
        
        if output_meta.with_masks is not None:
            st = st.with_masks(output_meta.with_masks, last_step=output_meta.step)
            output_path = st.masks_rel
        
        step_meta = dict(st.step_meta)
        meta: dict[str, Any] = dict(step_meta.get(output_meta.step, {}))
        
        if output_meta.mark_failed:
            meta['status'] = "failed"
            
        if output_meta.mark_done:
            meta["axes"] = output_meta.axes
            if output_path is not None:
                meta["output_path"] = output_path.as_posix()
            
            chan_meta = meta.get("channels", {})
            
            for label in output_meta.output_labels:
                chan_meta[label] = {"status": "done",
                               "hashed_settings": output_meta.hashed_settings,}
            meta["channels"] = chan_meta
        
        step_meta[output_meta.step] = meta
        return replace(st, step_meta=step_meta, updated_at=datetime.now())

    
    