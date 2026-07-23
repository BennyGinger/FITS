# from collections.abc import Sequence
# from typing import Any

# from numpy.typing import NDArray

# from fits_io.client import FitsIO


# def get_array(reader: FitsIO, requested_channels: Sequence[str] = ("all",)) -> tuple[NDArray[Any], str]:
#     """
#     Get the correct array with the requested channels. It will also return the axis order of that array for downstream processing.
    
#     Policy:
#         - Only expect one series here; if multiple series are present, raise an error (this is not currently supported in the workflow).
#         - Will return the axis order of the returned array, which may be different from the original if channels are subset. For example, if original is "TCZYX" and channels are subset to 1 channel, returned axis order will be "TZXY" with C removed.
    
#     Parameters:
#         reader: FitsIO reader instance for the input image, used to access channel labels and retrieve arrays.
#         requested_channels: Sequence of channel labels to subset. Use ["all"] (default) to return all channels.
#     """
#     if len(requested_channels) == 1 and requested_channels[0] == "all":
#         array = reader.get_array()
#         axis_order = reader.axes[0]
#         if isinstance(array, list):
#             raise ValueError("Get_array does not support multi-series files.")
#         return array, axis_order

#     labels = reader.channel_labels
#     if labels is None:
#         raise ValueError("Input image has no channel labels; cannot resolve requested channels.")
    
#     if set(requested_channels) == set(labels):
#         array = reader.get_array()
#         axis_order = reader.axes[0]
#     else:
#         array = reader.get_channel_array(requested_channels)
#         axis_order = reader.axes[0].replace('C', '') if len(requested_channels) == 1 else reader.axes[0]
    
#     if isinstance(array, list):
#         raise ValueError("Get_array does not support multi-series files.")
    
#     return array, axis_order