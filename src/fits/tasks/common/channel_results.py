from pathlib import Path

import numpy as np
from fits_io.client import FitsIO
from fits_io.writers.apis import merge_channel_arrays
from fits_io.writers.models import ChannelMergeResult


def append_channel_result(results: ChannelMergeResult | None,
                        new_array: np.ndarray,
                        new_axes: str,
                        channel_index: int,
                        reference_axes: str,
                        ) -> ChannelMergeResult:
    """
    Add one processed channel to an in-memory channel result.
    """
    if results is None:
        return ChannelMergeResult(array=new_array,
                                axes=new_axes,
                                channel_indices=[channel_index],)
    return merge_channel_arrays(existing_array=results.array,
                                existing_axes=results.axes,
                                existing_channel_indices=results.channel_indices,
                                new_array=new_array,
                                new_axes=new_axes,
                                new_channel_indices=[channel_index],
                                reference_axes=reference_axes,)


def merge_channel_results(reader: FitsIO,
                        new_results: ChannelMergeResult | None,
                        output_path: Path | None,
                        overwrite: bool,) -> ChannelMergeResult:
    """
    Merge newly processed channels with an existing output artifact.
    """
    if new_results is None:
        raise ValueError("No pending channel results were resolved.")

    existing_reader = None
    if output_path is not None and not overwrite:
        existing_reader = FitsIO.from_path(output_path)

    return reader.merge_channels(existing=existing_reader,
                                new_array=new_results.array,
                                new_axes=new_results.axes,
                                new_channel_indices=new_results.channel_indices,)
