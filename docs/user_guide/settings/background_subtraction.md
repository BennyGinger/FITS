# Background subtraction

[Guide home](../README.md)

Related: [Preprocessing](../preprocessing.md) · [Background preview](../tools/background_subtraction.md) · [Shared settings](common.md) · [Measurement columns](../output_tables.md)

Remove estimated image background before segmentation or measurement. Open
**Preprocess → Background subtraction**. Use the preview to inspect the residual
signal on representative planes.

## Settings

| Parameter | Practical meaning |
| --- | --- |
| Window size (>=2) | SMO background-estimation window, in pixels. Choose a size appropriate to the structures to keep. |
| Sigma | Gaussian smoothing used by background estimation. |
| Exclude channels | Keep selected channels' values unchanged. Multiple selection is allowed. |
| Threshold (0–1) | Probability threshold used by the background estimator. |
| Statistic | Median or mean for the background calculation. |
| Background execution / workers | Within-image background-processing parallelism, separate from experiment workers. |
| Preview | Inspect corrected planes and compare original/corrected intensities without writing pipeline outputs. |

## Output

Writes `proc_array_bgsub.tif` with signed `float32` values. Negative and fractional
residuals are retained for measurements; display copies can show negatives as
zero. This step changes intensities, so it does not invalidate REF/ROI geometry.
