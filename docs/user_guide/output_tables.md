# Understanding the output tables

[User guide](README.md) · [Analysis and results](analysis_and_results.md)

FITS saves its measurements as **Parquet (`.parquet`) files**. Each file contains
a table that can be opened in Tad, Data Wrangler, or Python as a dataframe.
This reference describes columns produced by the current exporters; older saved
results can have fewer columns until the relevant analysis is rerun.
The column lists describe populated results; outputs without detected objects
can be empty and need not contain every optional measurement column.

## Which file should I open?

| File | Location | Contents |
| --- | --- | --- |
| `fits_quantification.parquet` | Each experiment/series folder | Object shape, intensity, reference distance, and tracking measurements. |
| `master_quantification.parquet` | Run folder | The available experiment quantification tables combined, with folder-based condition tags. |
| `fits_distance_profile.parquet` | Each experiment/series folder | Image intensity summarized in distance bins around a reference mask. |
| `master_distance_profile.parquet` | Run folder | The available experiment distance profiles combined, with folder-based condition tags. |

Only enabled analyses with available results produce their corresponding tables.
The two master tables are different products, not interchangeable versions of
one dataframe. Master tables combine experiment rows; they do not average them.

## Units, missing values, and dimensions

- **Frame numbers start at 1; time starts at 0 seconds.** Time is calculated as
  `(frame - 1) × acquisition interval`, rather than a separate timestamp for each frame.
- **Pixel coordinates start at 0.** X is the image column and Y is the image row.
  Centroids can have fractional coordinates.
- **Intensity uses the stored image values**, including preprocessing. It is not
  normalized by display contrast or converted to a universal fluorescence unit.
  Background-corrected measurements can be negative.
- **Physical distances require valid, equal X/Y pixel sizes.** Without usable
  isotropic calibration, pixel distances remain available but µm distances are
  missing. Shape measurements such as `area` and `perimeter` stay in pixel units.
- **Missing is not zero.** Empty cells in a table viewer, `NaN`, `None`, and
  pandas `NA` can represent missing or undefined values. Their display/storage
  representation varies. Types below describe the values, not a guaranteed
  pandas dtype or integer bit width.
- **These analyses are currently 2D.** With a Z stack, FITS maximum-projects
  images and object labels before quantification; binary reference/ROI masks
  use inclusion across Z. Distance profiles also use a maximum-projected image.
  Quantification does not export `centroid_z` or a Z-plane identity column.

## Quantification: what does one row represent?

One row describes **one labeled object in one frame, measured in one intensity
channel and one compartment**, with one reference name/channel combination
when references exist.

FITS uses the active tracking mask when available, otherwise the segmentation
mask. It measures every intensity channel in the selected analysis image and
every channel in the selected object-mask artifact. These are different roles:
a GFP-derived mask can have both GFP and RFP intensity measurements.

Rows repeat across intensity channels, compartments, and reference combinations.
For example, one cell in one frame, two intensity channels, three compartments,
and one reference combination produces **six rows**, not six cells. With two
reference combinations, it produces twelve. Without a reference, the reference
columns are absent and measurements are still produced.

Saved REF masks are discovered even when requesting new reference drawing is
disabled. **ROI masks currently restrict distance-profile measurements, not
object quantification.** Their presence does not filter quantification rows.

### Identity and acquisition columns

| Column | Type / units | Meaning and availability |
| --- | --- | --- |
| `experiment_id` | Text | Acquisition-local ID in current per-experiment exports, such as `sample/sample_s1`; normalized to the full run-relative path, such as `control/sample/sample_s1`, in masters. Present in both table types. |
| `cell_id` | Text | Portable object identifier combining experiment, object type, object channel, and numeric label. Segmentation IDs also include frame. Shared across intensity channels, references, and compartments. |
| `object_name` | Text | `tracking` or `segmentation`: the mask artifact used for extraction. Accepted tracking edits still have the `tracking` object type. |
| `object_channel` | Text, possibly missing | Channel label belonging to the object-mask array; identifies where the masks came from. |
| `label` | Integer | Nonzero object ID stored in the mask. Background label 0 is not measured. Labels alone are not unique across experiments or mask channels. |
| `frame` | Integer, 1-based | Frame containing this object observation. |
| `time_sec` | Number or missing, seconds | Relative acquisition time. Missing when the acquisition interval is unavailable; a zero interval produces zero times. |
| `intensity_channel` | Text, possibly missing | Image channel from which this row's `intensity_mean` was measured. |
| `compartment` | Text | `full`, `mb` (membrane), or `cyto` (cytoplasm). Always present in new quantification outputs; only `full` when compartment measurement is disabled. |

For tracked objects, `cell_id` follows a track through time. For segmentation
objects, the same numeric label in another frame does not establish cell
continuity. Treat `cell_id` as an opaque grouping key; its encoding and examples
are explained in [Analysis identifiers](analysis_identifiers.md).

### Default shape and intensity measurements

| Column | Type / units | Meaning |
| --- | --- | --- |
| `area` | Number, pixel² | Area of the measured compartment. With unit pixel spacing this is its included-pixel count. |
| `centroid_x` | Number, pixels | X coordinate of the full-cell geometric centroid, not an intensity-weighted centroid. |
| `centroid_y` | Number, pixels | Y coordinate of the same full-cell centroid. |
| `perimeter` | Number, pixels | The compartment's boundary-length estimate from scikit-image. |
| `solidity` | Number, dimensionless | Compartment area divided by its convex-hull area. Values near 1 indicate a region that fills its convex hull. |
| `intensity_mean` | Number, stored intensity units | Arithmetic mean of image pixels inside this compartment, in the row's intensity channel. It is not total/integrated intensity. |

These defaults use scikit-image's
[region measurements](https://scikit-image.org/docs/stable/api/skimage.measure.html#skimage.measure.regionprops).
FITS supplies no physical spacing to these shape measurements, so it does not
automatically add `area_um2`, `perimeter_um`, or calibrated centroid columns.

When compartments are enabled, optional expansion first defines `full`; `mb`
and `cyto` divide that region. Shape and intensity measurements describe the
row's compartment, while **all compartments share the full-cell centroid and
reference distances**. The compartment geometry preserves the original labels.

The cytoplasm retains at least one pixel per cell, even if the requested
membrane thickness would otherwise consume it. A singleton full cell can
therefore have an empty membrane: its membrane area, perimeter, and intensity
measurements are zero; undefined extra shape measurements can be missing.

### Reference-distance columns

These four columns are added when reference masks are supplied. With no
reference mask, they are absent rather than filled with zero.

| Column | Type / units | Meaning |
| --- | --- | --- |
| `ref_label_name` | Text | Reference name, for example `edge` from `fits_ref_edge.tif`. |
| `ref_channel` | Text, possibly missing | Channel stored in the reference mask; independent of object and intensity channels. |
| `dist_pixel` | Number or missing, pixels | Distance from the full-cell centroid's integer pixel position to the nearest included reference pixel. |
| `dist_um` | Number or missing, µm | `dist_pixel × pixel size`; missing without usable isotropic calibration. |

The fractional centroid coordinates are truncated to the integer pixel used to
sample a Euclidean distance map. This is **not** a distance between cell and
reference centroids, nor an average distance over all cell pixels. A centroid
inside the reference has distance zero. An empty reference frame produces missing
distances for that reference. A single-frame reference is reused across time.

### Track bounds and duration in frames

These columns are always added by current FITS extraction. They are populated
for `tracking` rows and missing for `segmentation` rows.

| Column | Type / units | Meaning |
| --- | --- | --- |
| `track_start_frame` | Nullable integer, frame number | First extracted frame for this `cell_id`. |
| `track_end_frame` | Nullable integer, frame number | Last extracted frame for this `cell_id`. |
| `track_length` | Nullable integer, frames | Inclusive span: `track_end_frame - track_start_frame + 1`. Includes gaps. |

A track observed only in frames 3 and 8 has `track_length = 6`, although it has
two observations. A track spanning 271 consecutive frames has 270 time intervals.
These statistics use the final extracted observations and repeat across all
rows belonging to the same track.

### Tracking motion columns

All columns below exist in current FITS quantification exports. Their values
are missing for segmentation rows. Spatially calibrated columns additionally
require isotropic pixel calibration; speeds require positive elapsed time.

| Pixel column | Calibrated column | Meaning |
| --- | --- | --- |
| `step_dist_pixel` (pixels) | `step_dist_um` (µm) | Straight-line centroid displacement from the previous observed frame; zero for the first observation. |
| `step_speed_pixel_per_s` (pixels/s) | `step_speed_um_per_s` (µm/s) | Step displacement divided by elapsed time since the previous observation; missing for the first observation or a nonpositive/missing elapsed time. |
| `track_total_dist_pixel` (pixels) | `track_total_dist_um` (µm) | Sum of the observed step displacements over the track. |
| `track_displacement_pixel` (pixels) | `track_displacement_um` (µm) | Straight-line distance between the first and last observed centroids. |
| `track_mean_speed_pixel_per_s` (pixels/s) | `track_mean_speed_um_per_s` (µm/s) | Total observed distance divided by the time between first and last observations. This is not an unweighted average of the step-speed rows. |
| `track_start_ref_dist_pixel` (pixels) | `track_start_ref_dist_um` (µm) | Reference distance at the track's first observed frame, for this reference name/channel. |
| `track_end_ref_dist_pixel` (pixels) | `track_end_ref_dist_um` (µm) | Reference distance at the track's last observed frame, for this reference name/channel. |

These are numbers, with missing values for undefined measurements. Each
calibrated value is its pixel counterpart multiplied by the pixel size.

| Column | Type / units | Meaning |
| --- | --- | --- |
| `Dp` | Number or missing, dimensionless | Path straightness: `track_displacement_pixel / track_total_dist_pixel`. Zero means return to the starting point after moving; 1 means a straight observed path. |
| `Dw` | Number or missing, dimensionless | Reference approach: `(track_start_ref_dist_pixel - track_end_ref_dist_pixel) / track_total_dist_pixel`. Positive means net approach; negative means net retreat. |

`Dp` and `Dw` are missing for zero total movement. Without references, the
endpoint-reference columns and `Dw` are still present but missing. Each
endpoint distance uses its own frame's reference mask: changing the reference
can change `Dw`, even without a corresponding change in the cell trajectory.
Values are not clipped; moving/changing references can produce `Dw` outside
−1 to 1. Missing endpoint distances
are not replaced with distances from another frame.

Steps join consecutive **observed** positions, even across gaps. Speeds across
a gap use the full elapsed time; FITS does not reconstruct unobserved detours.
Whole-track metrics repeat across frames, intensity channels, and compartments;
reference-specific metrics additionally vary by reference name/channel.

### Optional extra measurements

`additional_properties` adds requested
[scikit-image region properties](https://scikit-image.org/docs/stable/api/skimage.measure.html#skimage.measure.regionprops_table)
to the default measurements. There is no fixed additional-column list: it
depends on the requested properties and their array dimensions.

For example, `eccentricity` adds a dimensionless shape value. In 2D, `bbox`
expands to `bbox_0`, `bbox_1`, `bbox_2`, and `bbox_3`: minimum Y, minimum X,
exclusive maximum Y, and exclusive maximum X, in pixels. Tensor/vector
properties similarly expand into indexed columns. Extra measurements describe
the measured compartment unless otherwise specified; the default centroid
columns continue to describe the full cell.

Only the default `intensity_mean` is converted into the long-form
`intensity_channel` layout. Other requested multichannel intensity properties
can retain indexed names such as `intensity_max_0` and `intensity_max_1` on
each row; their indices refer to input image channel order.

### Small quantification example

This synthetic example has one tracked cell (`label = 7`, object channel GFP),
two frames, two intensity channels, one reference (`edge`, reference channel RFP),
and three compartments. The rows below are a subset of its twelve rows; all
share one `cell_id`. Frame interval is 5 s and pixel size is 0.5 µm.

| `frame` | `time_sec` | `intensity_channel` | `compartment` | `area` | `intensity_mean` | `dist_pixel` |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 0 | GFP | full | 16 | 20 | 5 |
| 1 | 0 | RFP | full | 16 | 40 | 5 |
| 1 | 0 | GFP | mb | 12 | 20 | 5 |
| 1 | 0 | GFP | cyto | 4 | 20 | 5 |
| 2 | 5 | GFP | full | 16 | 30 | 4 |
| 2 | 5 | RFP | full | 16 | 60 | 4 |

The centroid moved one pixel toward the reference. Thus `track_length = 2`,
`track_total_dist_pixel = 1`, `track_mean_speed_pixel_per_s = 0.2`, and
`Dp = Dw = 1`. Reference distances in µm are 2.5 and 2.0.

## Distance profiles: what does one row represent?

One row describes **one distance bin, in one frame and intensity channel,
against one reference name/channel, for one ROI variant**. These are image-pixel
statistics, not individual-cell measurements; the table has no `cell_id`, object
label, or compartment column.

FITS always calculates a whole-image variant, with missing `roi_label_name` and
`roi_channel`, **as well as** each saved ROI name/channel variant. The reference
defines distances; the ROI only chooses which pixels contribute to statistics.
Pixels inside the reference have distance zero and can contribute to bin 0.

### Distance-profile columns

| Column | Type / units | Meaning and availability |
| --- | --- | --- |
| `experiment_id` | Text | Acquisition-local experiment ID, normalized to a full run-relative path in the master, as in quantification. |
| `frame` | Integer, 1-based | Image frame used for this profile. |
| `time_sec` | Number or missing, seconds | `(frame - 1) × acquisition interval`; missing when unavailable. |
| `channel` | Text, possibly missing | Measured image intensity channel. This table uses `channel`, not quantification's `intensity_channel`. |
| `ref_label_name` | Text | Reference name derived from its saved filename. |
| `ref_channel` | Text, possibly missing | Reference-mask channel used for the distance map. |
| `roi_label_name` | Text or missing | ROI name; missing for the whole-image variant. |
| `roi_channel` | Text or missing | ROI-mask channel; missing for the whole-image variant. |
| `z_projection` | Text or missing | `max` when a Z stack was maximum-projected; missing when the input had no Z axis. |
| `bin` | Integer, 0-based | Distance-bin index; independent of the frame numbering convention. |
| `dist_start_px` | Number, pixels | Lower edge of the distance bin. |
| `dist_end_px` | Number, pixels | Upper edge of the distance bin. |
| `dist_px` | Number, pixels | Bin centre: `(dist_start_px + dist_end_px) / 2`. |
| `dist_start_um` | Number or missing, µm | Lower bin edge multiplied by pixel size. |
| `dist_end_um` | Number or missing, µm | Upper bin edge multiplied by pixel size. |
| `dist_um` | Number or missing, µm | Bin centre multiplied by pixel size. |
| `mean_intensity` | Number or missing, stored intensity units | Mean of finite image intensities among the included pixels in the bin. |
| `std_intensity` | Number or missing, stored intensity units | Population standard deviation of those intensities (`ddof = 0`), not standard error. |
| `pixel_count` | Integer, pixels | Number of finite-intensity pixels contributing to the bin. Zero for an empty bin. |

### Bin boundaries and empty bins

`bin_width` is in pixels. With width 2, bins are `[0, 2)`, `[2, 4)`, `[4, 6)`,
and so on. `maximum_bins = 3` limits the output to bins 0–2 and excludes
distances of 6 pixels or more. Without a limit, the range covers the selected
pixels' maximum distance.

Within an experiment, profiles are padded to the largest calculated bin count
so frames/channels/ROI variants align. A bin can therefore exist even when it
has no contributing pixels. Empty or padded bins have **`pixel_count = 0` and
missing mean/standard deviation**, not zero fluorescence. Nonfinite image
intensities are excluded. A populated one-pixel bin has zero standard deviation.
An empty ROI produces empty-bin rows; an empty reference mask cannot define
a profile and causes an analysis error.

For example, a synthetic 12×12 image with a reference in column 0, uniform
intensity 20, and an ROI covering columns 0–2 gives:

| ROI variant | `bin` | Distance range (pixels) | `pixel_count` | `mean_intensity` | `std_intensity` |
| --- | --- | --- | --- | --- | --- |
| Whole image | 0 | [0, 2) | 24 | 20 | 0 |
| Whole image | 1 | [2, 4) | 24 | 20 | 0 |
| Whole image | 2 | [4, 6) | 24 | 20 | 0 |
| Columns 0–2 | 0 | [0, 2) | 24 | 20 | 0 |
| Columns 0–2 | 1 | [2, 4) | 12 | 20 | 0 |
| Columns 0–2 | 2 | [4, 6) | 0 | missing | missing |

## Master tables and condition columns

Current per-experiment tables use `acquisition/series` identifiers so the saved
scientific tables remain unchanged when their acquisition moves between
condition folders. The master exporter concatenates available experiment
tables, normalizes `experiment_id` to the full current run-relative path, and
adds folder-derived tags. Master quantification also rebuilds `cell_id` with
that full experiment ID. Older individual tables may retain an earlier ID form.

For example, a per-experiment ID `sample/sample_s1` becomes
`control/sample/sample_s1` in the master when its acquisition is under `control/`.
Use master IDs when combining acquisitions: identical acquisition names under
different conditions can share an acquisition-local ID.

The master adds:

| Column pattern | Type | Meaning |
| --- | --- | --- |
| `condition_level_1` | Text or missing | Outermost user-created condition folder below the run folder. |
| `condition_level_2`, `condition_level_3`, … | Text or missing | Successive nested condition folders. The number of columns depends on the deepest included experiment. |

For `run/control/drugA/sample/sample_s1/`, where `sample/` is FITS's acquisition
folder, the conditions are `control` and `drugA`; the structural acquisition and
series folders are not condition tags. Shallower experiments receive missing
values for deeper levels. With no condition folders, no condition columns are
needed. These tags belong to master exports: fresh per-experiment analysis
exports do not add them. Location-only updates regenerate master tags while
leaving portable individual Parquets unchanged. Legacy structure migration can
also remove old per-experiment condition columns when rewriting those tables.

Master quantification normalizes `cell_id` and recalculates track bounds/span
from the saved observations. It preserves existing motion measurements, but
does not calculate missing motion columns in legacy experiment tables. Combining
tables with different optional columns can create missing values in the master.

The standard per-experiment Parquets also contain file-level FITS provenance,
such as input revisions and processing settings. Those are **metadata, not
dataframe columns**. Master export does not carry the same per-experiment FITS
metadata payload; keep the experiment artifacts and settings for provenance.

For the readable metadata embedded in TIFF images and masks, see
[Inspecting artifact metadata in ImageJ/Fiji](viewers.md#inspecting-artifact-metadata-in-imagejfiji).

## Grouping without double-counting

- **Tracked cells:** count distinct `cell_id` values among tracking rows, rather
  than counting rows. Across separate runs, also retain a run identifier.
- **Cell observations per frame:** select the desired object type, then use one
  observation per `(cell_id, frame)` after choosing any needed channel/reference filters.
- **Intensity curves:** select the intended `intensity_channel` and `compartment`,
  and select a reference combination if several duplicate the same intensity rows.
- **Track summaries:** take one value per `cell_id`, or per
  `(cell_id, ref_label_name, ref_channel)` for reference-dependent summaries.
- **Distance profiles:** select the intended `channel`, reference combination,
  and ROI variant. Do not mix whole-image rows with ROI rows unintentionally.
  An overall pixel-weighted mean across populated bins is
  `sum(mean_intensity × pixel_count) / sum(pixel_count)`, not the unweighted mean
  of their means; exclude empty bins from that calculation.

Updating FITS or rebuilding a master does not remeasure edited images or masks.
Rerun quantification or distance profiling with overwrite when its numerical
inputs change. See [Reprocessing and file management](reprocessing_and_file_management.md).

## Implementation references

Column definitions were checked against the current exporters:

- [Region properties and compartments](../../bioimagequant/src/bioimagequant/extraction/regions.py),
  [column formatting](../../bioimagequant/src/bioimagequant/extraction/formatting.py), and
  [reference distances](../../bioimagequant/src/bioimagequant/extraction/distances.py).
- [FITS quantification export](../../src/fits/tasks/analysis/extraction/extract.py),
  [identity and conditions](../../src/fits/tasks/analysis/identity.py),
  [track spans](../../src/fits/tasks/analysis/tracking_summary.py), and
  [motion](../../src/fits/tasks/analysis/tracking_motion.py).
- [Distance-profile columns](../../bioimagequant/src/bioimagequant/distance_profile/table.py),
  [bin statistics](../../bioimagequant/src/bioimagequant/distance_profile/binning.py), and
  [FITS profile adapter](../../src/fits/tasks/analysis/dist_profile/manager.py).
- [Master aggregation](../../src/fits/tasks/analysis/aggregate.py) and
  [per-experiment Parquet metadata](../../src/fits/tasks/common/table_results.py).
