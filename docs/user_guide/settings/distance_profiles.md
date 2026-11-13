# Distance profile

[Guide home](../README.md)

Related: [Analysis overview](../analysis_and_results.md) · [Reference drawing](../tools/reference_masks.md) · [ROI drawing](../tools/roi_masks.md) · [Mask collection](../tools/mask_collection.md) · [Output tables](../output_tables.md) · [Shared settings](common.md)

Summarise intensity in distance bins around a reference mask. Open
**Analysis → Distance profile**.

## Settings

| Parameter | Practical meaning |
| --- | --- |
| Expected REF masks | At least one nonempty reference is required for distance profiling. |
| Draw ROI masks / Expected ROI masks | Optionally restrict profiles to saved ROI variants. |
| Bin width | Positive distance-bin width in pixels. |
| Maximum bins | Optional limit on the number of bins; None leaves it unlimited. |

## Distance profiles

Enable **Distance profile** to summarize image intensity in distance bins around a saved reference. Provide at least one nonempty REF mask; use the [drawing workflow](../reference_and_roi_masks.md) when new masks are needed. Set `bin_width` in pixels and optionally `maximum_bins`. FIScH calculates the whole-image profile as well as profiles for each saved ROI variant. See [distance-profile columns](../output_tables.md#distance-profiles-what-does-one-row-represent) for bin edges, empty bins, ROI variants, and calibrated distances.

## Output

Each series saves `proc_distance_profile.parquet`; active-series results are
combined in the corresponding master table. The output-table guide describes
bin edges, calibrated distances, empty bins and ROI variants.
