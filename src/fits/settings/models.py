from collections.abc import Callable, Mapping, Sequence
from typing import Any, TypeVar

import numpy as np
from numpy.typing import NDArray
from fits_io.readers._types import Zproj
from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

from fits.environment.constant import ExecMode, STATISTIC_MAP, SUPPORTED_STATISTICS



class SettingsModel(BaseModel):
    """
    Pydantic base model for settings classes in the FITS pipeline.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    overwrite: bool = Field(default=False, exclude=True)


FitsSettings = TypeVar("FitsSettings", bound=SettingsModel)


class ConvertSettings(SettingsModel):
    """
    Settings for the conversion process in the FITS pipeline.
    
    Attributes:
        channel_labels: Optional list of channel labels in the image.
        export_channels: Channels to export; can be 'all' or a list of specific channels.
        filename: Optional filename for the converted output.
        custom_metadata: Optional mapping of user-defined metadata to include in the output.
        z_projection: Z-projection method to apply to the input files. Supported methods are: max, mean or None. By default, apply max projection.
        compression: Optional compression method for the output file.
        overwrite: Whether to overwrite existing files during conversion coming from SettingsModel.
        execution: Execution mode for the convert step: serial | thread | process. By default, it will use thread-based execution for this step.
        workers: Number of worker threads or processes to use for the convert step. This is only applicable if the execution mode is set to thread or process. If set to "None", it will use the default number of workers (which is typically the number of CPU plus four).
        ordered_execution: Whether to preserve the order of the input files in the output files when using parallel execution. If true, it will ensure that the output files are saved in the same order as the input files. If false, it may save output files in a different order than the input files, which can be faster but may not be desirable in some cases.
    """
    channel_labels: str | Sequence[str] | None = None
    export_channels: str | Sequence[str] = 'all'
    custom_metadata: Mapping[str, Any] | None = None
    z_projection: Zproj = 'max'
    compression: str | None = 'zlib'
    
    # Execution mode
    execution: ExecMode = Field(default="thread", exclude=True)
    workers: int | None = Field(default=None, exclude=True)
    ordered_execution: bool = Field(default=False, exclude=True)
    
    @field_validator('workers', mode='before')
    @classmethod
    def parse_workers(cls, v):
        if isinstance(v, str) and v.lower() == 'none':
            return None
        return v
    
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
    statistic: Callable[..., NDArray[Any]] = np.median
    
    # Execution mode
    execution: ExecMode = Field(default="thread", exclude=True)
    workers: int | None = Field(default=None, exclude=True)
    ordered_execution: bool = Field(default=False, exclude=True)

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


class SegmentSettings(SettingsModel):
    """
    Settings for the segmentation process in the FITS pipeline.
    
    Attributes:
        user_settings: Dictionary containing the settings for Cellpose given by the user.
        channel_to_segment: The channel(s) list to use for segmentation. This should match at least one of the channel labels in the input files.
        use_nuclear_channel: If True, configures for nuclear channel usage.
        do_denoise: If True, applies denoising to the input images.
        model: Optional pre-initialized Cellpose model instance to use instead of creating a new one. Default is None.
        overwrite: Whether to overwrite existing files during segmentation coming from SettingsModel.
        threading: If True, adds a lock for thread-safe inference. Will be automatically set to True if execution mode is 'thread'.
        execution: Execution mode for the convert step: serial | thread | process. By default, it will use thread-based execution for this step.
        workers: Number of worker threads or processes to use for the convert step. This is only applicable if the execution mode is set to thread or process. If set to "None", it will use the default number of workers (which is typically the number of CPU plus four).
        ordered_execution: Whether to preserve the order of the input files in the output files when using parallel execution. If true, it will ensure that the output files are saved in the same order as the input files. If false, it may save output files in a different order than the input files, which can be faster but may not be desirable in some cases.
    """
    channel_to_segment: Sequence[str] = Field(exclude=True)
    do_denoise: bool = True
    nuclear_channel: Sequence[str] = Field(default_factory=list, exclude=True)
    user_settings: dict[str, Any] = Field(default_factory=dict)
    model: Any | None = None  
    
    # Execution mode
    execution: ExecMode = Field(default="thread", exclude=True)
    workers: int | None = Field(default=None, exclude=True)
    ordered_execution: bool = Field(default=False, exclude=True)
    
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
        return len(self.nuclear_channel) > 0