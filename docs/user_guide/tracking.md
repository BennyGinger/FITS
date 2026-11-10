# Tracking and corrections

[User guide](README.md) · [Previous: Segmentation](segmentation.md) ·
[Next: Reference and ROI masks](reference_and_roi_masks.md)

Tracking links segmented objects through time. Start with a time series and usable segmentation masks; select the channels configured as segmentation targets in [Channels and labels](channels_and_labels.md#exported-channels-and-downstream-choices).

See the separate feature lists for the
[tracking viewer](gui_tools.md#tracking-viewer-gui) and
[tracking editor](gui_tools.md#tracking-editor-gui) for their selection, display,
filtering, and editing controls.

## Run tracking and inspect tracks

Select **Include in workflow** for Tracking in **Process**, select the segmented channels, and run the pipeline. Leave Tracking included with Overwrite unchecked to reuse valid saved tracks for Quantification. Bypassing Tracking makes Quantification use included Segmentation instead. Open `proc_masks_track.tif` in [Image / Mask Viewer](viewers.md) to inspect cell IDs, trajectories, and track-length filters. A segmentation label is a per-frame object; a tracking label links observations over time. Review suspicious identity switches and gaps before extracting measurements.

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

## Editing and saving tracking results

The main GUI temporarily hides the **Edit tracking** pipeline step. Instead,
use **Edit tracking** directly below **Image / Mask Viewer** in the run browser.
The button is available when the run contains saved tracking results and the
pipeline is idle. It opens the selected experiment's tracked result, or the
first tracked result in the run, in the existing standalone editor.

The displayed image
channel can be changed independently from the mask channel and is the channel
used by local mask prediction. **Save edited tracking** writes
`proc_track_edited.tif`, or `proc_track_edited_filtered.tif` when track-length
filtering is enabled. The original `proc_masks_track.tif` remains in place.
This standalone button does not include an editing stage in pipeline execution;
Quantification continues to follow the included workflow's mask source.

Standalone `fisch-trackedit /path/to/experiment/proc_array_raw.tif` starts an empty
tracking session without an existing tracking mask. Add/Edit uses headless
micro-SAM with positive/negative prompts and an expected cell diameter defining
the local crop. Predict, inspect or brush-correct the proposal, then accept it;
accepted masks determine the centroids used for trajectories. Manual brush and
enclosed-fill operations remain separate from inference, as does the Split
predictor. The editor supports track merge/link, stopping or unlinking a track,
mask/track deletion, and undo. Saves use the edited-tracking filenames above
and record compact edit provenance. Redo, a replayable per-edit log, and the
static-only temporal policy remain pending; see the
[tracking TODOs](../dev/todos.txt) and [micro-SAM cleanup plan](../dev/microsam_tracking_cleanup.md).

## Measurements after editing

After saving different masks, rerun quantification with overwrite so measurements use the active edited result. Rebuilding a master table alone does not remeasure masks. See [Output tables](output_tables.md) for track spans, motion, gaps, and repeated rows; see [viewer exports](viewers.md#exporting-overlays-and-cropping) for annotated TIFFs.
