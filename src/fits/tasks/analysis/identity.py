"""Portable experiment provenance and object identity for FITS measurements."""

from urllib.parse import quote
from typing import cast

import pandas as pd

from fits.environment.constant import ARTI_SEG, ARTI_TRACK


def add_quantification_ids(dataframe: pd.DataFrame, experiment_id: str) -> pd.DataFrame:
    """Return measurements with portable experiment and cell identifiers.

    Tracked labels identify a cell over time; segmentation labels identify an
    observation in one frame. Intensity channels never change cell identity.
    Delimiters in user labels are escaped to avoid ambiguous concatenation.
    Z is deliberately omitted while extraction uses a 2D maximum projection.
    """
    result = dataframe.copy()
    for column in ("experiment_id", "cell_id"):
        if column in result:
            result.pop(column)
    result.insert(0, "experiment_id", experiment_id)
    if result.empty:
        result.insert(1, "cell_id", pd.Series(index=result.index, dtype="string"))
        return result

    required = {"object_name", "object_channel", "label"}
    missing = required.difference(result.columns)
    if missing:
        raise ValueError(f"Cannot identify cells: missing columns {sorted(missing)}.")
    object_names = cast(pd.Series, result["object_name"])
    labels = cast(pd.Series, result["label"])
    if not object_names.isin([ARTI_TRACK, ARTI_SEG]).all():
        raise ValueError("Cell IDs require tracking or segmentation object names.")
    if labels.isna().any():
        raise ValueError("Cell IDs require non-null object labels.")

    # Encode each distinct channel once, including a separate null-channel form.
    channels = cast(pd.Series, result["object_channel"])
    channel_parts = {
        channel: "|channel=" + quote(str(channel), safe="")
        for channel in channels.dropna().unique()
    }
    ids = (
        quote(experiment_id, safe="/")
        + "|object=" + object_names.astype("string")
        + channels.map(channel_parts).fillna("|channel")
        + "|label=" + labels.astype("Int64").astype("string")
    )
    segmentation = object_names.eq(ARTI_SEG)
    if segmentation.any():
        if "frame" not in result or result.loc[segmentation, "frame"].isna().any():
            raise ValueError("Segmentation cell IDs require non-null frame numbers.")
        ids.loc[segmentation] += (
            "|frame=" + result.loc[segmentation, "frame"].astype("Int64").astype("string")
        )
    result.insert(1, "cell_id", ids)
    return result
