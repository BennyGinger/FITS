# Analysis identifiers

FITS adds portable `experiment_id` values to quantification and distance-profile
Parquets. The value is the complete experiment path relative to the run directory,
using `/` separators. For example:

```text
control/sample/sample_s1
treated/sample/sample_s1
```

Moving or renaming the complete run folder leaves these identifiers unchanged.
Changing the relative condition/acquisition/series path changes the identifier.
Different runs with identical relative layouts share this namespace; retain a
separate run identifier when combining them. Condition tags exclude the structural
acquisition folder: `control/sample/sample_s1` has the condition `control`.

Quantification also includes `cell_id`, built from `experiment_id`, `object_name`,
`object_channel`, and the numeric object `label`. Segmentation observations also
include `frame`, because segmentation labels can represent different cells in
different frames. Tracking identifiers omit frame and represent the same track
through time. They do not assert biological continuity beyond the tracking result.

```text
control/sample/sample_s1|object=tracking|channel=iRed|label=24
control/sample/sample_s1|object=segmentation|channel=iRed|label=24|frame=3
```

The measured `intensity_channel` is excluded: several intensity measurements of
one cell share its ID. Existing object labels and measurement columns are kept.
ID components escape reserved characters with percent encoding; use `cell_id` as
an opaque grouping/join key and keep the original columns for analysis. A missing
object-channel label uses `|channel` without `=`, distinct from an empty label.
Changing object-channel labels or reprocessing masks can change cell IDs.

New quantification tables always include `compartment`: `full` when compartment
extraction is disabled, or `full`, `mb` and `cyto` when enabled. Compartment and
intensity channel are excluded from cell identity; all measurements of one
parent cell share its `cell_id`. Optional dilation defines the full-cell region
before centroid measurement. All compartment rows share that full-cell centroid
and reference distances, so motion remains a property of the full cell.

Quantification also includes three nullable integer columns for tracking rows:

| Column | Meaning |
| --- | --- |
| `track_start_frame` | First frame containing the tracked cell (1-based). |
| `track_end_frame` | Last frame containing the tracked cell (1-based). |
| `track_length` | Inclusive span: `track_end_frame - track_start_frame + 1`. |

Gaps count towards the total length: a track present in frames 3 and 8 has a
length of 6 frames. Repeated intensity-channel measurements do not affect it.
Segmentation rows contain null values in these columns; a single-frame track has
length 1. FITS calculates these statistics per `cell_id` from the final extracted
measurements, reflecting mask edits and postprocessing when extraction is rerun.
Master aggregation also recalculates them from the available experiment tables.
Rerun extraction after editing masks to replace measurements from older masks;
aggregation alone cannot discover edits absent from the saved measurements.

Tracking extraction also adds motion measurements from the measured 2D centroids:

| Column | Meaning |
| --- | --- |
| `step_dist_pixel` | Straight-line distance from the previous observed centroid; first observation is 0. |
| `step_speed_pixel_per_s` | Step distance divided by elapsed seconds since the previous observation; first observation is null. |
| `track_total_dist_pixel` | Sum of observed step distances over the entire track. |
| `track_displacement_pixel` | Straight-line distance from the first observed centroid (S) to the last (E). |
| `track_mean_speed_pixel_per_s` | Total travelled distance divided by `last time_sec - first time_sec`. |
| `track_start_ref_dist_pixel` | Existing `dist_pixel` at S, for this reference name/channel. |
| `track_end_ref_dist_pixel` | Existing `dist_pixel` at E, for this reference name/channel. |
| `Dp` | Path straightness: `track_displacement_pixel / track_total_dist_pixel`. |
| `Dw` | Reference approach: `(track_start_ref_dist_pixel - track_end_ref_dist_pixel) / track_total_dist_pixel`. |

Each distance/speed column has a calibrated counterpart replacing `_pixel` with
`_um`, including `_um_per_s` speeds. Physical values require valid isotropic XY
pixel calibration. Speeds additionally require positive elapsed time. Missing
metadata leaves the corresponding values null. For a stationary track with
known positive duration, mean speed is 0; zero-duration tracks have null mean
speed. `Dp` and `Dw` are null when total travelled distance is 0.

Steps connect consecutive observed positions, even across missing frames. A
missing frame creates no measurement row; the next observation measures from
the last known centroid, and its speed uses the full elapsed time. Unknown
detours within a gap are not reconstructed, and no gap-count column is added.
Total duration measures intervals between endpoints: 271 consecutive frames
span 270 frame intervals, independently of the inclusive `track_length`.

`Dw` reuses distances to the nearest reference-mask pixel, rather than its
centroid. Each endpoint uses the reference mask from its respective frame, so
reference movement or shape changes affect `Dw` as well as cell movement.
Positive values mean approach, negative values mean retreat, and 0 means no
net change in reference distance. Values are not clipped; changing reference
masks can produce values outside the fixed-reference range. A missing reference
distance at an endpoint leaves that endpoint distance and `Dw` null.
Without a reference mask, all reference-dependent motion columns remain null.

FITS calculates each cell/frame once, then attaches step values and whole-track
summaries to the original intensity/reference rows. Whole-track values repeat
across those rows; `Dw` and endpoint-reference distances are specific to each
reference name/channel. Segmentation rows have null motion values. These
calculations use extracted measurements and do not depend on GUI caches.
Master aggregation preserves the new columns. Rerun extraction with overwrite
to add them to existing experiment tables; aggregation does not backfill motion
measurements into legacy outputs.

Z-plane identity is deferred. Extraction currently maximum-projects Z before
quantification, so each measurement describes a 2D projected object. If extraction
later supports independent Z-plane objects, include an explicit plane index in
their IDs to distinguish reused labels across planes. A 3D object's centroid Z
coordinate must not be used as its identity.

New extractions save both identifiers in each experiment's quantification file.
Aggregation rebuilds identifiers from the current run layout for the master
tables, including reused quantification files with the required object columns.
After reorganizing folders, **Manage files → Update paths and condition tags**
rewrites identifiers, known paths and tags in individual experiment files and
regenerates masters without changing measurements or data revisions. This does
not refresh measurements after image/mask changes; rerun extraction for those.
Already-running Python processes
need restarting to use updated code; existing Parquets are not changed simply
by updating FITS.

Standalone Python callers should pass `run_dir` to `ExperimentState.init()` or
`load_experiment_state()` when working with nested experiments. Without it, a
single experiment uses its work folder's name. Pipeline discovery supplies this
context automatically and reconstructs it when loading a moved run; no absolute
run root is persisted in experiment-state JSON.
