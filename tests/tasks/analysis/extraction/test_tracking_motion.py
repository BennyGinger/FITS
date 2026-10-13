"""Motion uses observed tracks, not duplicated intensity/reference rows."""

import numpy as np
import pandas as pd
import pytest

from fits.tasks.analysis.tracking_motion import MOTION_COLUMNS, PIXEL_COLUMNS, add_track_motion


def measurements() -> pd.DataFrame:
    rows = []
    for frame, x, y, near, far in [(2, 0, 0, 9, 4), (3, 3, 4, 5, 8), (5, 3, 0, 6, 10)]:
        for intensity in ("GFP", "RFP"):
            for name, distance, channel in (("near", near, None), ("far", far, "GFP")):
                rows.append({
                    "object_name": "tracking", "cell_id": "experiment|tracking|iRed|24",
                    "frame": frame, "centroid_x": float(x), "centroid_y": float(y),
                    "time_sec": (frame - 1) * 2, "intensity_channel": intensity,
                    "ref_label_name": name, "ref_channel": channel, "dist_pixel": float(distance),
                })
    table = pd.DataFrame(rows).sample(frac=1, random_state=4)
    table.index = table.index * 3 + 20
    return table


def test_steps_spans_reference_groups_and_calibration_preserve_original_rows() -> None:
    table = measurements()
    original = table.copy(deep=True)
    add_track_motion(table, pixel_size=0.5)
    pd.testing.assert_frame_equal(table[original.columns], original)
    for frame, step, speed in [(2, 0, np.nan), (3, 5, 2.5), (5, 4, 1)]:
        rows = table.loc[table["frame"] == frame]
        np.testing.assert_allclose(rows["step_dist_pixel"], step)
        np.testing.assert_allclose(rows["step_speed_pixel_per_s"], speed)
    np.testing.assert_allclose(table["track_total_dist_pixel"], 9)
    np.testing.assert_allclose(table["track_displacement_pixel"], 3)
    np.testing.assert_allclose(table["track_mean_speed_pixel_per_s"], 1.5)
    np.testing.assert_allclose(table["Dp"], 1 / 3)
    for reference, start, end, dw in [("near", 9, 6, 1 / 3), ("far", 4, 10, -2 / 3)]:
        rows = table.loc[table["ref_label_name"] == reference]
        np.testing.assert_allclose(rows["track_start_ref_dist_pixel"], start)
        np.testing.assert_allclose(rows["track_end_ref_dist_pixel"], end)
        np.testing.assert_allclose(rows["Dw"], dw)
    for column in PIXEL_COLUMNS:
        np.testing.assert_allclose(table[column.replace("_pixel", "_um")],
                                   table[column] * 0.5, equal_nan=True)


@pytest.mark.parametrize("timing", ["absent", "null", "zero"])
def test_missing_timing_keeps_distances_and_missing_calibration_keeps_pixel_metrics(timing) -> None:
    table = measurements().drop(columns=["ref_label_name", "ref_channel", "dist_pixel"])
    if timing == "absent":
        table = table.drop(columns="time_sec")
    else:
        table["time_sec"] = pd.NA if timing == "null" else 0
    add_track_motion(table)
    np.testing.assert_allclose(table["track_total_dist_pixel"], 9)
    np.testing.assert_allclose(table["Dp"], 1 / 3)
    missing = [name for name in MOTION_COLUMNS if "_um" in name or "speed" in name
               or "ref_dist" in name or name == "Dw"]
    assert table[missing].isna().to_numpy().all()


def test_stationary_single_observation_and_segmentation_rows() -> None:
    table = pd.DataFrame({
        "object_name": ["tracking"] * 3 + ["segmentation"],
        "cell_id": ["still", "still", "single", "seg"], "frame": [1, 2, 4, 1],
        "centroid_x": [3, 3, 5, np.nan], "centroid_y": [4, 4, 6, np.nan],
        "time_sec": [0, 2, 6, 0], "dist_pixel": [5, 4, 2, 3],
        "ref_label_name": ["wound"] * 4, "ref_channel": [None] * 4,
    })
    add_track_motion(table, pixel_size=0.5)
    np.testing.assert_allclose(table.loc[:2, "track_total_dist_pixel"], 0)
    assert table.loc[:2, ["Dp", "Dw"]].isna().to_numpy().all()
    assert table.loc[1, "step_speed_pixel_per_s"] == 0
    assert table.loc[0, "track_mean_speed_pixel_per_s"] == 0
    assert np.isnan(table.loc[2, "track_mean_speed_pixel_per_s"])
    assert table.loc[3, list(MOTION_COLUMNS)].isna().all()


def test_missing_endpoint_reference_distance_is_not_replaced_with_later_distance() -> None:
    table = measurements()
    table.loc[(table["frame"] == 2) & (table["ref_label_name"] == "near"), "dist_pixel"] = np.nan
    add_track_motion(table)
    assert table.loc[table["ref_label_name"] == "near", "Dw"].isna().all()
    assert table.loc[table["ref_label_name"] == "near", "track_start_ref_dist_pixel"].isna().all()
    np.testing.assert_allclose(table.loc[table["ref_label_name"] == "far", "Dw"], -2 / 3)


def test_track_ids_remain_independent_and_rerunning_recomputes_removed_endpoints() -> None:
    table = measurements()
    other = table.copy()
    other["cell_id"] = "other-experiment|tracking|iRed|24"
    other[["centroid_x", "centroid_y"]] *= 2
    table = pd.concat([table, other], ignore_index=True)
    add_track_motion(table)
    np.testing.assert_allclose(table.iloc[:12]["track_total_dist_pixel"], 9)
    np.testing.assert_allclose(table.iloc[12:]["track_total_dist_pixel"], 18)
    edited = table.loc[table["frame"] != 5].copy()
    add_track_motion(edited)
    first = edited.loc[edited["cell_id"] == "experiment|tracking|iRed|24"]
    np.testing.assert_allclose(first["track_total_dist_pixel"], 5)
    np.testing.assert_allclose(first["Dp"], 1)
    np.testing.assert_allclose(first["track_mean_speed_pixel_per_s"], 2.5)


def test_empty_table_has_stable_motion_schema() -> None:
    table = pd.DataFrame()
    add_track_motion(table)
    assert list(table.columns) == list(MOTION_COLUMNS)
    assert table.empty


def test_closed_loop_has_zero_straightness_despite_nonzero_travel() -> None:
    table = measurements()
    table.loc[table["frame"] == 5, ["centroid_x", "centroid_y"]] = 0
    add_track_motion(table)
    np.testing.assert_allclose(table["track_total_dist_pixel"], 10)
    np.testing.assert_allclose(table["track_displacement_pixel"], 0)
    np.testing.assert_allclose(table["Dp"], 0)


def test_reference_channels_with_the_same_name_remain_independent() -> None:
    table = measurements()
    table["ref_label_name"] = "wound"
    add_track_motion(table)
    np.testing.assert_allclose(table.loc[table["ref_channel"].isna(), "Dw"], 1 / 3)
    np.testing.assert_allclose(table.loc[table["ref_channel"].notna(), "Dw"], -2 / 3)
