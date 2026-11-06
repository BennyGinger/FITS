# Analysis and results

[User guide](README.md) · [Previous: Reference and ROI masks](reference_and_roi_masks.md) ·
[Next: Reprocessing and file management](reprocessing_and_file_management.md)

Analysis produces object measurements and/or intensity profiles around references. [Understanding the output tables](output_tables.md) explains all standard columns, units, missing values, and grouping without double-counting.

## Choose the analysis inputs

Quantification uses the active tracking result when available, otherwise segmentation, together with the configured analysis image. Object-mask channels and measured intensity channels are different roles; see [Channels and labels](channels_and_labels.md#channel-names-in-the-output-dataframes). Saved reference masks add reference-distance measurements. ROI masks currently restrict distance profiles rather than object quantification.

## Quantification and compartments

Quantification includes portable experiment paths and cell identifiers for
grouping measurements across intensity channels and time. See
[analysis identifiers](analysis_identifiers.md) for their format, segmentation
behavior, and the deferred handling of independent Z planes.

Quantification can optionally measure cell compartments. Enable **Measure cell
compartments**, choose **Membrane thickness (pixels)** and optionally **Cell
expansion (pixels)**. Expansion preserves neighbouring labels without overlap
and defines the full-cell region before centroid measurement. Each cell is then
processed separately using a cropped distance transform, including where cells
touch. The `compartment` column contains `full`, `mb` and `cyto`; when disabled,
it contains only `full`. All compartments retain the parent cell identity,
full-cell centroid and reference distances. A fully eroded cytoplasm retains
one cell pixel nearest the full-cell centroid, excluded from the membrane.
Compartment masks are generated in memory during extraction. Enable **Save
compartment masks** to export `_mb.tif` and `_cyto.tif` beside the selected
segmentation/tracking mask using the FITS TIFF protocol. The source mask is
unchanged, including when dilation is enabled. Compaction removes these exports
while retaining source masks, measurements and settings. Rebuilding regenerates
them only when compartment measurement and saving remain enabled. Rerun extraction with overwrite to update existing
measurements.

The corresponding `[extract.params]` settings are `compartments = false`,
`membrane_thickness = 6.0` (finite and positive), `dilation_radius = 0.0`
(finite and non-negative), and `save_compartment_masks = false`. Both distances
are in pixels.


For the controls shared with segmentation, see [segmentation and compartment previews](segmentation.md#segmentation-and-compartment-previews).

## Distance profiles

Enable **Distance profile** to summarize image intensity in distance bins around a saved reference. Provide at least one nonempty REF mask; use the [drawing workflow](reference_and_roi_masks.md) when new masks are needed. Set `bin_width` in pixels and optionally `maximum_bins`. FITS calculates the whole-image profile as well as profiles for each saved ROI variant. See [distance-profile columns](output_tables.md#distance-profiles-what-does-one-row-represent) for bin edges, empty bins, ROI variants, and calibrated distances.

## Open the results

Run the enabled analyses and read the completion report. Each series saves its own `fits_quantification.parquet` and/or `fits_distance_profile.parquet`; the run folder contains the corresponding master tables. Double-click a Parquet in the run browser to open optional [Tad](installation.md#optional-tad-installation), or use the Data Wrangler alternative described there. Master tables combine rows rather than averaging cells. Use [Analysis identifiers](analysis_identifiers.md) to distinguish experiments and cells.

## When to rerun analysis

After changing images, object masks, or references, rerun the affected analysis with overwrite. Updating software or aggregating old tables does not update their numerical measurements. Missing physical calibration leaves the corresponding physical-distance values empty; read the [output conventions](output_tables.md#units-missing-values-and-dimensions) before interpreting null or repeated values.
