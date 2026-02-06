from typing import Any, Mapping, Sequence, TypeVar

from fits_io.image_reader import Zproj
from pydantic import BaseModel


class SettingsModel(BaseModel):
    """
    Pydantic base model for settings classes in the FITS pipeline.
    """

    overwrite: bool = False


FitsSettings = TypeVar("FitsSettings", bound=SettingsModel)


class ConvertSettings(SettingsModel):
    """
    Settings for the conversion process in the FITS pipeline.
    
    Attributes:
        channel_labels: Optional list of channel labels in the image.
        export_channels: Channels to export; can be 'all' or a list of specific channels.
        filename: Optional filename for the converted output.
        user_defined_metadata: Optional mapping of user-defined metadata to include in the output.
        compression: Optional compression method for the output file.
        overwrite: Whether to overwrite existing files during conversion coming from SettingsModel.
    """
    channel_labels: str | Sequence[str] | None = None
    export_channels: str | Sequence[str] = 'all'
    user_defined_metadata: Mapping[str, Any] | None = None
    z_projection: Zproj = 'max'
    compression: str | None = 'zlib'
    

if __name__ == "__main__":
    from fits.settings._dev import dev_settings
    
    conv = ConvertSettings.model_validate(dev_settings)
    print(conv.model_dump())