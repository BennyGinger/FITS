from collections.abc import Callable, Mapping, Sequence
from typing import Any, Literal, TypeVar

import numpy as np
from numpy.typing import NDArray
from fits_io.readers._types import Zproj
from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from fits.environment.constant import ExecMode, TimeRegiContext, ChannelRegiContext, STATISTIC_MAP, SUPPORTED_STATISTICS


############### Base settings model ############

class SettingsModel(BaseModel):
    """
    Pydantic base model for settings classes in the FITS pipeline.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    overwrite: bool = Field(default=False, exclude=True)
    execution: ExecMode = Field(default="thread", exclude=True)
    workers: int | None = Field(default=None, exclude=True)
    ordered_execution: bool = Field(default=False, exclude=True)

    @field_validator('workers', mode='before', check_fields=False)
    @classmethod
    def parse_workers(cls, v):
        if isinstance(v, str) and v.lower() == 'none':
            return None
        return v


FitsSettings = TypeVar("FitsSettings", bound=SettingsModel)

############# Conversion settings ############

class ConvertSettings(SettingsModel):
    """
    Settings for the conversion process in the FITS pipeline.
    
    Attributes:
        channel_labels: Optional list of channel labels in the image.
        export_channels: Channels to export; can be 'all' or a list of specific channels.
        filename: Optional filename for the converted output.
        z_projection: Z-projection method to apply to the input files. Supported methods are: max, mean or None. By default, apply max projection.
        compression: Optional compression method for the output file.
        overwrite: Whether to overwrite existing files during conversion coming from SettingsModel.
        execution: Execution mode for the convert step: serial | thread | process. By default, it will use thread-based execution for this step.
        workers: Number of worker threads or processes to use for the convert step. This is only applicable if the execution mode is set to thread or process. If set to "None", it will use the default number of workers (which is typically the number of CPU plus four).
        ordered_execution: Whether to preserve the order of the input files in the output files when using parallel execution. If true, it will ensure that the output files are saved in the same order as the input files. If false, it may save output files in a different order than the input files, which can be faster but may not be desirable in some cases.
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
        if isinstance(v, str) and v.lower() == 'none':
            return None
        return v    

#### Registration settings and related constants ############

class RegisterSettings(SettingsModel):
    """Base settings for registration steps. Not meant to be used directly."""

    backend: Literal["scikit", "pystackreg", "cv2"] | None = None
    method: Literal["translation", "rigid_body", "affine"] | None = None

    @field_validator('fit_channel', 'reference_channel', mode='before', check_fields=False)
    @classmethod
    def parse_optional_channel(cls, v):
        if isinstance(v, str) and v.lower() == 'none':
            return None
        return v

    @field_validator('backend', 'method', mode='before')
    @classmethod
    def parse_optional_literals(cls, v):
        if isinstance(v, str) and v.lower() == 'none':
            return None
        return v
    

class RegisterTimeSettings(RegisterSettings):
    """Settings for time-wise registration (drift correction over time)."""
    context: TimeRegiContext = "linear_drift"
    reference_strategy: Literal["previous", "first", "mean"] = "previous"
    fit_channel: int | str | None = None

    workers: int | None = Field(default=1, exclude=True)
    
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
    """Settings for channel-wise registration (cross-channel alignment)."""
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
            return None if v.lower() == 'none' else [v]
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
    """
    Settings for the background subtraction process in the FITS pipeline.
    
    Attributes:
        sigma: The standard deviation for Gaussian kernel used in background estimation. Default is 0.0, which means no smoothing.
        size: The size of the neighborhood used for background estimation. Default is 3.
        threshold: The threshold value for background subtraction. Default is 0.05.
        statistic: The statistic function to use for background estimation. Default is np.median.
        execution: Execution mode for the convert step: serial | thread | process. By default, it will use thread-based execution for this step.
        workers: Number of worker threads or processes to use for the convert step. This is only applicable if the execution mode is set to thread or process. If set to "None", it will use the default number of workers (which is typically the number of CPU plus four).
        ordered_execution: Whether to preserve the order of the input files in the output files when using parallel execution. If true, it will ensure that the output files are saved in the same order as the input files. If false, it may save output files in a different order than the input files, which can be faster but may not be desirable in some cases.
        overwrite: Whether to overwrite existing files during background subtraction coming from SettingsModel.
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
    bg_workers: int | None = Field(default=None, exclude=True) # i.e. how many threads to use for the bg_sub() call

    @field_validator('exclude_channel', mode='before')
    @classmethod
    def parse_exclude_channel(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            return None if v.lower() == 'none' else [v]
        return list(v)

    @field_validator('mask', mode='before', check_fields=False)
    @classmethod
    def parse_mask(cls, v):
        if v is None:
            return None
        if isinstance(v, str) and v.lower() == 'none':
            return None
        if isinstance(v, np.ndarray):
            return v.astype(bool, copy=False)
        return np.asarray(v, dtype=bool)

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
    """
    Settings for the segmentation process in the FITS pipeline.
    
    Attributes:
        channel_to_segment: The channel(s) list to use for segmentation. This should match at least one of the channel labels in the input files.
        do_denoise: If True, applies denoising to the input images.
        nuclear_channel: The channel(s) list to use as nuclear channel(s) for segmentation. If specified, it will enable nuclear channel mode in Cellpose.
        user_settings: Dictionary containing the settings for Cellpose given by the user.
        model: Optional pre-initialized Cellpose model instance to use instead of creating a new one. Default is None.
        overwrite: Whether to overwrite existing files during segmentation coming from SettingsModel.
        threading: If True, adds a lock for thread-safe inference. Will be automatically set to True if execution mode is 'thread'.
        execution: Execution mode for the convert step: serial | thread | process. By default, it will use thread-based execution for this step.
        workers: Number of worker threads or processes to use for the convert step. This is only applicable if the execution mode is set to thread or process. If set to "None", it will use the default number of workers (which is typically the number of CPU plus four).
        ordered_execution: Whether to preserve the order of the input files in the output files when using parallel execution. If true, it will ensure that the output files are saved in the same order as the input files. If false, it may save output files in a different order than the input files, which can be faster but may not be desirable in some cases.
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
############# Tracking settings ############

class TrackSettings(SettingsModel):
    """
    Settings for the tracking process in the FITS pipeline.
    
    Attributes:
        channel_to_track: The channel(s) list to use for tracking. This should match at least one of the channel labels in the input files.
        backend: The tracking backend to use. Supported options are 'trackastra' and 'to_be_dev'. Default is 'trackastra'.
        filter_by_length: Minimum track length in frames to keep after tracking. Tracks shorter than this length will be filtered out. Default is 0 (no filtering).
        user_settings: Dictionary containing the settings for the chosen tracking backend given by the user. The specific settings will depend on the backend used.
        overwrite: Whether to overwrite existing files during tracking coming from SettingsModel.
    """
    channel_to_track: Sequence[str] = Field(exclude=True)
    backend: str = "trackastra"
    filter_by_length: int = 0
    workers: int | None = Field(default=1, exclude=True)
    
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