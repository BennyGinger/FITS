# Quantification

[Guide home](../README.md)

Related: [Analysis overview](../analysis_and_results.md) · [Compartment preview](../tools/compartments.md) · [Reference drawing](../tools/reference_masks.md) · [Output tables](../output_tables.md) · [Shared settings](common.md)

Measure objects using included segmentation/tracking masks and the analysis
image. Open **Analysis → Quantification**.

## Settings

| Parameter | Practical meaning |
| --- | --- |
| Draw reference masks / Expected REF masks | Request reference drawings when distance measurements are needed. Saved drawings can be reused. |
| Additional properties | Optional extra measurement properties beyond the standard table columns. |
| Measure cell compartments | Add membrane and cytoplasm measurements alongside the full-cell measurements. |
| Membrane thickness | Positive distance in pixels defining the membrane region. |
| Cell expansion | Non-negative expansion in pixels before compartment geometry is calculated. |
| Save compartment masks | Export membrane/cytoplasm TIFFs during quantification; previewing does not export them. |
| Compartments → Preview | Open the separate compartment preview to inspect geometry. |
| Frame workers (advanced) | Parallelism within an experiment, separate from experiment workers. |

## Choose the analysis inputs

Quantification follows the included mask-producing workflow: included tracking takes priority, otherwise included segmentation supplies masks, together with the configured analysis image. Bypassing Tracking also bypasses its saved output. Object-mask channels and measured intensity channels are different roles; see [Channels and labels](../channels_and_labels.md#channel-names-in-the-output-dataframes). Saved reference masks add reference-distance measurements. ROI masks currently restrict distance profiles rather than object quantification.

## Quantification and compartments

Quantification includes portable experiment paths and cell identifiers for
grouping measurements across intensity channels and time. See
[analysis identifiers](../analysis_identifiers.md) for their format, segmentation
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
segmentation/tracking mask using the FIScH TIFF protocol. The source mask is
unchanged, including when dilation is enabled. Compaction removes these exports
while retaining source masks, measurements and settings. Rebuilding regenerates
them only when compartment measurement and saving remain enabled. Rerun extraction with overwrite to update existing
measurements.

The corresponding `[extract.params]` settings are `compartments = false`,
`membrane_thickness = 6.0` (finite and positive), `dilation_radius = 0.0`
(finite and non-negative), and `save_compartment_masks = false`. Both distances
are in pixels.


For the controls shared with segmentation, see [segmentation and compartment previews](../tools/segmentation.md#working-with-segmentation-previews).

## Output

Each series saves `proc_quantification.parquet`; the run combines active-series
results into the corresponding master table. Rerun quantification with overwrite
after changing measurement inputs/settings. Updating a master alone does not
remeasure objects.
