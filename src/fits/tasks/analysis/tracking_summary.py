"""Track spans derived from the final extracted object measurements."""

from typing import cast

import pandas as pd

from fits.environment.constant import ARTI_TRACK


def add_track_statistics(dataframe: pd.DataFrame) -> None:
    """Add nullable track bounds and inclusive length to a measurement table.

    Mutates the supplied table, which must already contain FITS cell IDs.
    Recomputes existing statistics; segmentation rows remain null. The span
    includes missing intermediate frames and is shared by all intensity rows.
    """
    for column in ("track_length", "track_start_frame", "track_end_frame"):
        dataframe[column] = pd.Series(pd.NA, index=dataframe.index, dtype="Int64")
    if dataframe.empty:
        return

    tracking = cast(pd.Series, dataframe["object_name"]).eq(ARTI_TRACK)
    if not tracking.any():
        return
    if "frame" not in dataframe:
        raise ValueError("Track statistics require frame numbers.")
    tracks = dataframe.loc[tracking, ["cell_id", "frame"]].copy()
    frames = cast(pd.Series, tracks["frame"])
    if frames.isna().any():
        raise ValueError("Track statistics require non-null frame numbers.")
    tracks["frame"] = frames.astype("Int64")
    grouped = tracks.groupby("cell_id", sort=False)["frame"]
    starts = grouped.transform("min")
    ends = grouped.transform("max")
    dataframe.loc[tracking, "track_start_frame"] = starts
    dataframe.loc[tracking, "track_end_frame"] = ends
    dataframe.loc[tracking, "track_length"] = ends - starts + 1
