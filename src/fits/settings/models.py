from typing import Any, Mapping, Sequence, TypeVar

from fits_io.readers._types import Zproj
from pydantic import BaseModel, field_validator, Field

from fits.environment.constant import ExecMode


class SettingsModel(BaseModel):
    """
    Pydantic base model for settings classes in the FITS pipeline.
    """

    overwrite: bool = Field(default=False, exclude=True)


FitsSettings = TypeVar("FitsSettings", bound=SettingsModel)


class ConvertSettings(SettingsModel):
    """
    Settings for the conversion process in the FITS pipeline.
    
    Attributes:
        channel_labels: Optional list of channel labels in the image.
        export_channels: Channels to export; can be 'all' or a list of specific channels.
        filename: Optional filename for the converted output.
        user_defined_metadata: Optional mapping of user-defined metadata to include in the output.
        z_projection: Z-projection method to apply to the input files. Supported methods are: max, mean or None. By default, apply max projection.
        compression: Optional compression method for the output file.
        overwrite: Whether to overwrite existing files during conversion coming from SettingsModel.
        execution: Execution mode for the convert step: serial | thread | process. By default, it will use thread-based execution for this step.
        workers: Number of worker threads or processes to use for the convert step. This is only applicable if the execution mode is set to thread or process. If set to "None", it will use the default number of workers (which is typically the number of CPU plus four).
        ordered_execution: Whether to preserve the order of the input files in the output files when using parallel execution. If true, it will ensure that the output files are saved in the same order as the input files. If false, it may save output files in a different order than the input files, which can be faster but may not be desirable in some cases.
    """
    channel_labels: str | Sequence[str] | None = None
    export_channels: str | Sequence[str] = 'all'
    user_defined_metadata: Mapping[str, Any] | None = None
    z_projection: Zproj = 'max'
    compression: str | None = 'zlib'
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
    

