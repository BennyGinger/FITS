# Tracking

[Guide home](../README.md)

Related: [Overview](../tracking.md) · [Processing workflow](../first_analysis.md) · [File Viewer](../tools/tracking_viewer.md) · [Tracking editor](../tools/tracking_editor.md) · [Shared settings](common.md)

Link segmented objects through time. Open **Process → Tracking** after producing
usable segmentation masks for a time series.

## Settings

| Parameter | Practical meaning |
| --- | --- |
| Channels to track | Choose channels configured as segmentation targets, rather than all converted channels. Multiple selection is allowed. |
| Repair masks and tracks | Optional repair for static or nearly static cells; keep it off for freely moving cells. |
| Minimum mask consistency (0–1) | Required shape consistency when matching and reconstructing static cells. |
| Minimum appearances | Minimum observed appearances for the static-cell reference. |
| Extrapolate start / end | Extend repaired masks toward the recording endpoints when enabled. |
| Algo / Trackastra options (advanced) | Tracking implementation, linking mode, pretrained model and maximum linking distance. |

## Run tracking and inspect tracks

Select **Include in workflow** for Tracking in **Process**, select the segmented channels, and run the pipeline. Leave Tracking included with Overwrite unchecked to reuse valid saved tracks for Quantification. Bypassing Tracking makes Quantification use included Segmentation instead. Open `proc_masks_track.tif` in [Image / Mask Viewer](../viewers.md) to inspect cell IDs, trajectories, and track-length filters. A segmentation label is a per-frame object; a tracking label links observations over time. Review suspicious identity switches and gaps before extracting measurements.

## Optional static-cell mask repair

Tracking's optional **Repair masks and tracks** is for static or nearly static cells.
It builds a reference from consistently occupied pixels and rejects weak,
ambiguous, or unmatched observations before interpolating the resulting gaps.
**Minimum mask consistency** controls observed-mask Dice similarity and its
equivalent IoU for identity matching and reconstructed masks; the minimum IoU
is always at least 0.5. After collision clipping, a reconstructed mask must still
overlap its intended shape sufficiently. Tiny fragments do not count as completed
cells. Tracks that cannot be completed over the requested interval are removed.
Existing tracking files require rerunning Tracking with overwrite to apply these
rules; downstream measurements must then be regenerated.

## Output and inspection

Writes `proc_masks_track.tif`. Use File Viewer to inspect identities and paths;
open Tracking editor separately to correct masks or links. Edited files have
separate names. Include/Overwrite and execution controls are described in Shared settings.
