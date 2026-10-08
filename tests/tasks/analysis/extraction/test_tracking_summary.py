"""Inclusive track lengths from final measurements, including missing frames."""

import pandas as pd
import pytest

from fits.tasks.analysis.identity import add_quantification_ids
from fits.tasks.analysis.tracking_summary import add_track_statistics


def measurements() -> pd.DataFrame:
    """Reused labels in different channels and segmentation, with a track gap."""
    table = pd.DataFrame({
        "object_name": ["tracking"] * 5 + ["segmentation"],
        "object_channel": ["iRed"] * 4 + ["GFP", "iRed"],
        "label": [24] * 6,
        "frame": [3, 3, 8, 8, 5, 3],
        "intensity_channel": ["GFP", "RFP", "GFP", "RFP", "GFP", "GFP"],
    })
    return add_quantification_ids(table, "run/sample")


def test_spans_include_gaps_and_ignore_repeated_intensity_measurements() -> None:
    table = measurements()
    add_track_statistics(table)
    assert table["track_length"].iloc[:5].tolist() == [6, 6, 6, 6, 1]
    assert table["track_start_frame"].iloc[:5].tolist() == [3, 3, 3, 3, 5]
    assert table["track_end_frame"].iloc[:5].tolist() == [8, 8, 8, 8, 5]
    assert table[["track_length", "track_start_frame", "track_end_frame"]].iloc[5].isna().all()
    assert str(table["track_length"].dtype) == "Int64"


def test_statistics_recalculate_after_removing_last_observations() -> None:
    table = measurements()
    add_track_statistics(table)
    edited = table.loc[table["frame"] != 8].copy()
    add_track_statistics(edited)
    assert edited["track_length"].iloc[:3].tolist() == [1, 1, 1]
    assert edited["track_end_frame"].iloc[:3].tolist() == [3, 3, 5]


def test_empty_table_has_nullable_statistics_columns() -> None:
    table = add_quantification_ids(pd.DataFrame(), "run/sample")
    add_track_statistics(table)
    for column in ("track_length", "track_start_frame", "track_end_frame"):
        assert table[column].empty
        assert str(table[column].dtype) == "Int64"


@pytest.mark.parametrize("missing_column", [True, False])
def test_missing_tracking_frame_fails_clearly(missing_column: bool) -> None:
    table = measurements()
    if missing_column:
        table = table.drop(columns="frame")
    else:
        table.loc[0, "frame"] = None
    with pytest.raises(ValueError, match="frame numbers"):
        add_track_statistics(table)
