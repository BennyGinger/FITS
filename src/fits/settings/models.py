from collections.abc import Callable, Sequence
from typing import Any, Literal, TypeVar

import numpy as np
from numpy.typing import NDArray
from fits_io.readers._types import Zproj
from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from fits.environment.constant import ExecMode, TimeRegiContext, ChannelRegiContext, STATISTIC_MAP, SUPPORTED_STATISTICS


############### Base settings model ############

class SettingsModel(BaseModel):
    """Shared execution settings for FITS workflow steps.

    Attributes:
        overwrite: Recompute a step even when its output is already complete.
        execution: Experiment-level execution mode used by the batch workflow.
        workers: Maximum experiment-level workers. ``None`` delegates the
            worker count to the selected executor.
        ordered_execution: Preserve input experiment order when collecting
            results from a parallel batch executor.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    overwrite: bool = Field(default=False, exclude=True)
    execution: ExecMode = Field(default="thread", exclude=True)
    workers: int | None = Field(default=None, ge=1, exclude=True)
    ordered_execution: bool = Field(default=False, exclude=True)

    @field_validator('workers', mode='before', check_fields=False)
    @classmethod
    def parse_workers(cls, v):
        if isinstance(v, str) and v.strip().lower() == 'none':
            return None
        return v


FitsSettings = TypeVar("FitsSettings", bound=SettingsModel)

############# Conversion settings ############

class ConvertSettings(SettingsModel):
    """Settings for converting source images into FITS image artifacts.

    Attributes:
        channel_labels: Optional source-channel labels, in source channel order.
            A single string is normalized to a one-item sequence.
        export_channels: Channel labels to retain, or ``"all"`` to retain every
            channel.
        z_projection: Z projection applied while loading the source image.
        compression: TIFF compression passed to the output writer. The string
            ``"None"`` is normalized to ``None``.

    Inherited attributes:
        overwrite: Recompute conversion even when its output already exists.
        execution: Experiment-level execution mode. Defaults to ``"thread"``.
        workers: Maximum experiment-level workers. ``None`` uses the executor
            default.
        ordered_execution: Preserve input experiment order when collecting
            parallel results. Defaults to ``False``.
    """
    channel_labels: str | Sequence[str] | None = None
    export_channels: str | Sequence[str] = 'all'
    z_projection: Zproj = 'max'
    compression: str | None = 'zlib'
    
    @field_validator('channel_labels', mode='before')
    @classmethod
    def parse_channel_labels(cls, v):
        if isinstance(v, str):
            return [v]
        return v
    
    @field_validator('compression', mode='before')
    @classmethod
    def parse_compression(cls, v):
        if isinstance(v, str) and v.strip().lower() == 'none':
            return None
        return v    

#### Registration settings and related constants ############

class RegisterSettings(SettingsModel):
    """Common backend overrides for registration settings.

    Attributes:
        backend: Optional registration backend override. ``None`` lets the
            registration context choose its backend.
        method: Optional transform-method override. ``None`` lets the
            registration context choose its method.

    Inherited attributes:
        overwrite: Recompute registration even when its output already exists.
        execution: Experiment-level execution mode. Defaults to ``"thread"``
            unless a subclass overrides it.
        workers: Maximum experiment-level workers. ``None`` uses the executor
            default unless a subclass overrides it.
        ordered_execution: Preserve input experiment order when collecting
            parallel results. Defaults to ``False``.

    This model is intended to be subclassed rather than used directly.
    """

    backend: Literal["scikit", "pystackreg", "cv2"] | None = None
    method: Literal["translation", "rigid_body", "affine"] | None = None

    @field_validator('fit_channel', 'reference_channel', mode='before', check_fields=False)
    @classmethod
    def parse_optional_channel(cls, v):
        if isinstance(v, str) and v.strip().lower() == 'none':
            return None
        return v

    @field_validator('backend', 'method', mode='before')
    @classmethod
    def parse_optional_literals(cls, v):
        if isinstance(v, str) and v.strip().lower() == 'none':
            return None
        return v
    

class RegisterTimeSettings(RegisterSettings):
    """Settings for time-wise registration and drift correction.

    Attributes:
        context: Registration scenario used to resolve default backend and
            transform method.
        reference_strategy: Frame reference used to estimate transforms.
        fit_channel: Channel index or label used to estimate transforms. A
            value of ``None`` delegates channel selection to the backend.

    Inherited attributes:
        backend: Optional registration backend override.
        method: Optional transform-method override.
        overwrite: Recompute time registration even when its output exists.
        execution: Experiment-level execution mode. Defaults to ``"serial"``.
        workers: Maximum experiment-level workers. Defaults to ``1`` and is
            ignored during serial execution.
        ordered_execution: Preserve input experiment order when collecting
            parallel results. Defaults to ``False``.
    """
    context: TimeRegiContext = "linear_drift"
    reference_strategy: Literal["previous", "first", "mean"] = "previous"
    fit_channel: int | str | None = None

    execution: ExecMode = Field(default="serial", exclude=True)
    workers: int | None = Field(default=1, ge=1, exclude=True)
    
    def to_payload_dict(self) -> dict[str, Any]:
        """
        Convert the RegisterTimeSettings instance to a metadata dictionary suitable for serialization.
        Excludes any fields that are not relevant for metadata.
        """
        payload = {
            "backend": self.backend,
            "method": self.method,
            "context": self.context,
            "reference_strategy": self.reference_strategy,
            "fit_channel": self.fit_channel,
        }
        return payload


class RegisterChannelSettings(RegisterSettings):
    """Settings for cross-channel registration.

    Attributes:
        context: Registration scenario used to resolve default backend and
            transform method.
        reference_channel: Channel index or label used as the fixed channel.
        exclude_channel: Channel labels excluded from registration.
        reference_frame: Frame index used to estimate channel transforms.

    Inherited attributes:
        backend: Optional registration backend override.
        method: Optional transform-method override.
        overwrite: Recompute channel registration even when its output exists.
        execution: Experiment-level execution mode. Defaults to ``"thread"``.
        workers: Maximum experiment-level workers. ``None`` uses the executor
            default.
        ordered_execution: Preserve input experiment order when collecting
            parallel results. Defaults to ``False``.
    """
    context: ChannelRegiContext = "channel_shift"
    reference_channel: int | str | None = None
    exclude_channel: list[str] | None = None
    reference_frame: int = 0
    
    @field_validator('exclude_channel', mode='before')
    @classmethod
    def parse_exclude_channel(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            return None if v.strip().lower() == 'none' else [v]
        return list(v)

    @model_validator(mode='after')
    def validate_reference_not_excluded(self) -> 'RegisterChannelSettings':
        if isinstance(self.reference_channel, str) and self.exclude_channel and self.reference_channel in self.exclude_channel:
            raise ValueError(f"reference_channel '{self.reference_channel}' cannot be excluded in register_channel.exclude_channel.")
        return self
    
    def to_payload_dict(self) -> dict[str, Any]:
        """
        Convert the RegisterChannelSettings instance to a metadata dictionary suitable for serialization.
        Excludes any fields that are not relevant for metadata.
        """
        payload = {
            "backend": self.backend,
            "method": self.method,
            "context": self.context,
            "reference_channel": self.reference_channel,
            "exclude_channel": list(self.exclude_channel) if self.exclude_channel else None,
            "reference_frame": self.reference_frame,
        }
        return payload

############ Background subtraction settings ############

class BGSubSettings(SettingsModel):
    """Settings for image background subtraction.

    Attributes:
        sigma: Gaussian smoothing sigma used during background estimation.
        size: Neighborhood size used to estimate the background.
        threshold: Background-subtraction threshold.
        exclude_channel: Channel labels copied without background subtraction.
        statistic: Callable used to summarize the local background. The strings
            ``"median"`` and ``"mean"`` are resolved to NumPy callables.
        bg_execution: Internal execution mode passed to :func:`bg_sub.bg_sub`.
        bg_workers: Maximum workers used internally by :func:`bg_sub.bg_sub`.

    Inherited attributes:
        overwrite: Recompute background subtraction even when its output exists.
        execution: Experiment-level execution mode. Defaults to ``"serial"``
            to avoid nesting it with the internal frame executor.
        workers: Maximum experiment-level workers. ``None`` uses the executor
            default and is ignored during serial execution.
        ordered_execution: Preserve input experiment order when collecting
            parallel results. Defaults to ``False``.
    """
    sigma: float = 0.0
    size: int = 3
    threshold: float = 0.05
    exclude_channel: list[str] | None = None
    statistic: Callable[..., NDArray[Any]] = np.median
    
    # NOTE: Background subtraction manages its own frame-level threading.
    # Therefore this FITS step defaults to serial experiment execution to
    # avoid nested executors. Revisit only if future benchmarks suggest
    # experiment-level parallelism performs better.
    execution: ExecMode = Field(default="serial", exclude=True) # i.e. how to run the task
    bg_execution: Literal["sequential", "thread"] = Field(default="thread", exclude=True) # i.e. how it's processed within the task
    bg_workers: int | None = Field(default=None, ge=1, exclude=True) # i.e. how many threads to use for the bg_sub() call

    @field_validator('exclude_channel', mode='before')
    @classmethod
    def parse_exclude_channel(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            return None if v.strip().lower() == 'none' else [v]
        return list(v)

    @field_validator("bg_workers", mode="before")
    @classmethod
    def parse_bg_workers(cls, value):
        if isinstance(value, str) and value.strip().lower() == "none":
            return None
        return value

    @field_validator('statistic', mode='before')
    @classmethod
    def parse_statistic(cls, v):
        if isinstance(v, str):
            key = v.strip().lower()
            if key in STATISTIC_MAP:
                return STATISTIC_MAP[key]
            raise ValueError(f"Unsupported statistic '{v}'. Supported values: {SUPPORTED_STATISTICS}.")
        if callable(v):
            return v
        raise TypeError(f"statistic must be a callable or one of: {SUPPORTED_STATISTICS}, got {type(v).__name__}.")

    def serialize_statistic_name(self) -> str:
        """Return a JSON-safe statistic name for metadata serialization."""
        name = getattr(self.statistic, "__name__", None)
        if isinstance(name, str) and name:
            return name
        return str(self.statistic)
    
    def to_payload_dict(self) -> dict[str, Any]:
        """
        Convert the BGSubSettings instance to a metadata dictionary suitable for serialization.
        Excludes any fields that are not relevant for metadata.
        """
        payload = {
            "sigma": self.sigma,
            "size": self.size,
            "threshold": self.threshold,
            "exclude_channel": list(self.exclude_channel) if self.exclude_channel else None,
            "statistic": self.serialize_statistic_name(),
        }
        return payload

############ Segmentation settings ############

class SegmentSettings(SettingsModel):
    """Settings for Cellpose-based image segmentation.

    Attributes:
        channel_to_segment: Channel labels to segment.
        do_denoise: Enable Cellpose denoising where supported by the installed
            Cellpose backend.
        nuclear_channel: Optional additional channel supplied as nuclear input.
        user_settings: Backend-specific Cellpose configuration.
        model: Optional pre-initialized Cellpose model.
        threading: Computed flag enabling the Cellpose inference lock when
            experiment-level execution uses threads.
        use_nuclear_channel: Computed flag indicating whether a nuclear channel
            was configured.

    Inherited attributes:
        overwrite: Recompute segmentation even when its output already exists.
        execution: Experiment-level execution mode. Defaults to ``"thread"``.
        workers: Maximum experiment-level workers. ``None`` uses the executor
            default.
        ordered_execution: Preserve input experiment order when collecting
            parallel results. Defaults to ``False``.
    """
    channel_to_segment: Sequence[str] = Field(exclude=True)
    do_denoise: bool = True
    nuclear_channel: str | None = Field(default=None, exclude=True)
    user_settings: dict[str, Any] = Field(default_factory=dict)
    model: Any | None = None  
    
    @computed_field()
    @property
    def threading(self) -> bool:
        """
        Returns True if the execution mode is set to 'thread', indicating that thread-safe inference should be used for Cellpose.
        """
        return self.execution == "thread"
    
    @computed_field()
    @property
    def use_nuclear_channel(self) -> bool:
        """
        Returns True if a nuclear channel is specified in the settings, indicating that nuclear channel mode should be enabled for Cellpose.
        """
        return self.nuclear_channel is not None
    
    def to_payload_dict(self) -> dict[str, Any]:
        """
        Convert the SegmentSettings instance to a metadata dictionary suitable for serialization.
        Excludes any fields that are not relevant for metadata.
        """
        payload = {"channel_to_segment": list(self.channel_to_segment),
                   "do_denoise": self.do_denoise,
                   "nuclear_channel": self.nuclear_channel,
                   "user_settings": self.user_settings,}
        return payload

    @field_validator('nuclear_channel', mode='before')
    @classmethod
    def parse_nuclear_chan(cls, v):
        if isinstance(v, str) and v.strip().lower() == 'none':
            return None
        return v

############# Tracking settings ############

class TrackSettings(SettingsModel):
    """Settings for converting segmentation masks into tracked labels.

    Attributes:
        channel_to_track: Segmentation channel labels to track.
        backend: Tracking backend name.
        filter_by_length: Minimum track length, in frames, retained in the
            output. Zero disables length filtering.
        trackastra: Configuration passed to the Trackastra backend.

    Inherited attributes:
        overwrite: Recompute tracking even when its output already exists.
        execution: Experiment-level execution mode. Defaults to ``"serial"``.
        workers: Maximum experiment-level workers. Defaults to ``1`` and is
            ignored during serial execution.
        ordered_execution: Preserve input experiment order when collecting
            parallel results. Defaults to ``False``.
    """
    channel_to_track: Sequence[str] = Field(exclude=True)
    backend: str = "trackastra"
    filter_by_length: int = Field(default=0, ge=0)

    execution: ExecMode = Field(default="serial", exclude=True)
    workers: int | None = Field(default=1, ge=1, exclude=True)

    # Backend specific settings
    trackastra: dict[str, Any] = Field(default_factory=dict)

    def to_payload_dict(self) -> dict[str, Any]:
        """
        Convert the TrackSettings instance to a metadata dictionary suitable for serialization.
        Excludes any fields that are not relevant for metadata.
        """
        payload = {
            "channel_to_track": list(self.channel_to_track),
            "backend": self.backend,
            "filter_by_length": self.filter_by_length,
            **getattr(self, self.backend, {}),
        }
        return payload

############# Distance-profile settings ############

class DistanceProfileSettings(SettingsModel):
    """Settings for binned intensity measurements from a reference mask.

    The analysis is strictly two-dimensional. FITS automatically max-projects
    any Z axis before profiling. Reference and ROI masks are collapsed across
    Z by including a pixel when it is included on any plane.

    FITS automatically profiles every intensity channel against every saved
    reference-mask label/channel. For each reference, it calculates both the
    whole-image profile and profiles for every saved ROI label/channel.

    Attributes:
        bin_width: Width of each distance bin in pixels.
        maximum_bins: Optional maximum number of distance bins to retain.
    """

    bin_width: float = Field(default=5.0, gt=0)
    maximum_bins: int | None = Field(default=None, ge=1)

    @field_validator("maximum_bins", mode="before")
    @classmethod
    def parse_optional_bin_count(cls, value):
        if isinstance(value, str) and value.strip().lower() in {"", "none"}:
            return None
        return value

####### Quantification settings ############

class ExtractSettings(SettingsModel):
    """Settings for region-based intensity quantification.

    Attributes:
        additional_properties: Extra scikit-image region properties appended to
            labelquant's defaults.
        frame_workers: Labelquant worker processes used to quantify frames
            within one experiment.

    Inherited attributes:
        overwrite: Recompute quantification even when its output already exists.
        execution: Experiment-level execution mode. Defaults to ``"serial"``
            to avoid nesting experiment and frame process pools.
        workers: Maximum experiment-level workers. ``None`` uses the executor
            default and is ignored during serial execution.
        ordered_execution: Preserve input experiment order when collecting
            parallel results. Defaults to ``False``.
    """
    additional_properties: str | Sequence[str] | None = None
    execution: ExecMode = Field(default="serial", exclude=True)
    frame_workers: int = Field(default=8, ge=1, exclude=True)

    @field_validator('additional_properties', mode='before')
    @classmethod
    def parse_properties(cls, v):
        if isinstance(v, str) and v.strip().lower() == 'none':
            return None
        return v
