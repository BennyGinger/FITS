"""Track motion from extracted centroids, without reading image or mask stacks."""

import numpy as np
import pandas as pd
from numpy.typing import NDArray
from typing import cast

from fits.environment.constant import ARTI_TRACK


PIXEL_COLUMNS = (
    "step_dist_pixel", "step_speed_pixel_per_s", "track_total_dist_pixel",
    "track_displacement_pixel", "track_mean_speed_pixel_per_s",
    "track_start_ref_dist_pixel", "track_end_ref_dist_pixel",
)
MOTION_COLUMNS = (*PIXEL_COLUMNS,
                  *(name.replace("_pixel", "_um") for name in PIXEL_COLUMNS), "Dp", "Dw")


def _divide(numerator: pd.Series, denominator: pd.Series) -> NDArray[np.float64]:
    """Undefined ratios (missing or nonpositive denominators) remain null."""
    top = numerator.to_numpy(dtype=np.float64, na_value=np.nan)
    bottom = denominator.to_numpy(dtype=np.float64, na_value=np.nan)
    result = np.full(len(top), np.nan)
    np.divide(top, bottom, out=result, where=np.isfinite(bottom) & (bottom > 0))
    return result


def _calibrate(table: pd.DataFrame, pixel_size: float | None) -> None:
    for name in PIXEL_COLUMNS:
        if name in table:
            table[name.replace("_pixel", "_um")] = (
                table[name] * pixel_size if pixel_size is not None else np.nan)


def _motion_tables(observations: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Compute each observed step once, and each complete track once."""
    observations = observations.sort_values(["cell_id", "frame"], kind="stable").copy()
    grouped = observations.groupby("cell_id", sort=False)
    delta = grouped[["centroid_x", "centroid_y"]].diff()
    first_observation = grouped.cumcount().eq(0)
    observations["step_dist_pixel"] = np.hypot(delta["centroid_x"], delta["centroid_y"])
    observations.loc[first_observation, "step_dist_pixel"] = 0.0
    observations["step_speed_pixel_per_s"] = _divide(
        cast(pd.Series, observations["step_dist_pixel"]),
        cast(pd.Series, grouped["time_sec"].diff()))

    starts = grouped.head(1).set_index("cell_id")
    ends = grouped.tail(1).set_index("cell_id").reindex(starts.index)
    summary = pd.DataFrame(index=starts.index)
    summary["track_start_frame"] = starts["frame"]
    summary["track_end_frame"] = ends["frame"]
    summary["track_total_dist_pixel"] = grouped["step_dist_pixel"].sum()
    summary["track_displacement_pixel"] = np.hypot(
        ends["centroid_x"] - starts["centroid_x"],
        ends["centroid_y"] - starts["centroid_y"])
    total_distance = cast(pd.Series, summary["track_total_dist_pixel"])
    duration = cast(pd.Series, ends["time_sec"]) - cast(pd.Series, starts["time_sec"])
    summary["track_mean_speed_pixel_per_s"] = _divide(total_distance, duration)
    summary["Dp"] = _divide(cast(pd.Series, summary["track_displacement_pixel"]), total_distance)

    metrics = observations[["cell_id", "frame", "step_dist_pixel", "step_speed_pixel_per_s"]]
    metrics = metrics.join(summary.drop(columns=["track_start_frame", "track_end_frame"]),
                           on="cell_id")
    return metrics.set_index(["cell_id", "frame"]), summary


def _reference_table(rows: pd.DataFrame, summary: pd.DataFrame) -> pd.DataFrame:
    """Use the existing reference distances at the actual track endpoints.

    Each distance uses its own frame's reference mask. Changes in that mask's
    position or shape therefore affect Dw as well as the cell's movement.
    """
    keys = ["cell_id", "ref_label_name", "ref_channel"]
    references = cast(pd.DataFrame, rows[[*keys, "frame", "dist_pixel"]])
    references = references.drop_duplicates([*keys, "frame"])
    frames = cast(pd.Series, references["frame"])
    cell_ids = cast(pd.Series, references["cell_id"])
    starts = frames.eq(cell_ids.map(cast(pd.Series, summary["track_start_frame"])))
    ends = frames.eq(cell_ids.map(cast(pd.Series, summary["track_end_frame"])))
    start_distances = references.loc[starts].set_index(keys)["dist_pixel"]
    end_distances = references.loc[ends].set_index(keys)["dist_pixel"]
    result = pd.concat([
        start_distances.rename("track_start_ref_dist_pixel"),
        end_distances.rename("track_end_ref_dist_pixel"),
    ], axis=1)
    total_distance = pd.Series(
        result.index.get_level_values("cell_id").map(cast(pd.Series, summary["track_total_dist_pixel"])),
        index=result.index)
    progress = (cast(pd.Series, result["track_start_ref_dist_pixel"])
                - cast(pd.Series, result["track_end_ref_dist_pixel"]))
    result["Dw"] = _divide(progress, total_distance)
    return result


def add_track_motion(dataframe: pd.DataFrame, *, pixel_size: float | None = None) -> None:
    """Add motion measurements to tracking rows; segmentation rows remain null.

    Intensity/reference rows share one centroid observation per cell and frame.
    Steps connect successive observed positions, including across gaps. Speeds
    use actual timestamp differences; no missing observations are invented.
    """
    for name in MOTION_COLUMNS:
        dataframe[name] = np.nan
    if dataframe.empty:
        return
    tracking = cast(pd.Series, dataframe["object_name"]).eq(ARTI_TRACK)
    if not tracking.any():
        return
    if pixel_size is not None and (not np.isfinite(pixel_size) or pixel_size <= 0):
        raise ValueError("Tracking motion requires a positive, finite pixel size.")

    position_columns = ["cell_id", "frame", "centroid_x", "centroid_y"]
    missing = set(position_columns).difference(dataframe.columns)
    if missing:
        raise ValueError(f"Tracking motion requires columns {sorted(missing)}.")
    extra_columns = [name for name in ("time_sec", "dist_pixel", "ref_label_name", "ref_channel")
                     if name in dataframe]
    rows = dataframe.loc[tracking, [*position_columns, *extra_columns]]
    observation_columns = [*position_columns, *(["time_sec"] if "time_sec" in rows else [])]
    observations = rows[observation_columns].drop_duplicates(["cell_id", "frame"]).copy()
    if observations["cell_id"].isna().any():
        raise ValueError("Tracking motion requires non-null cell IDs.")
    coordinates = observations[["frame", "centroid_x", "centroid_y"]].to_numpy(
        dtype=np.float64, na_value=np.nan)
    if not np.isfinite(coordinates).all():
        raise ValueError("Tracking motion requires finite frames and centroid coordinates.")
    if "time_sec" in rows:
        times = cast(pd.Series, pd.to_numeric(cast(pd.Series, observations["time_sec"])))
        observations["time_sec"] = times.to_numpy(dtype=np.float64, na_value=np.nan)
    else:
        observations["time_sec"] = np.nan

    motion, summary = _motion_tables(observations)
    _calibrate(motion, pixel_size)
    matched = rows[["cell_id", "frame"]].join(motion, on=["cell_id", "frame"])
    dataframe.loc[tracking, motion.columns] = matched[motion.columns].to_numpy()

    reference_keys = ["cell_id", "ref_label_name", "ref_channel"]
    if {"dist_pixel", *reference_keys}.issubset(rows.columns):
        reference_motion = _reference_table(rows, summary)
        _calibrate(reference_motion, pixel_size)
        # Merge columns rather than a nullable MultiIndex: reference channel
        # labels can legitimately be absent, including for every reference.
        matched = rows[reference_keys].merge(
            reference_motion.reset_index(), on=reference_keys, how="left",
            sort=False, validate="many_to_one")
        dataframe.loc[tracking, reference_motion.columns] = matched[reference_motion.columns].to_numpy()
