# Tracking editor

[Guide home](../README.md)

Related: [Tracking overview](../tracking.md) · [File Viewer](tracking_viewer.md) · [Output tables](../output_tables.md) · [Settings](../settings/tracking.md) · [All tools](../gui_tools.md) · [Viewer controls](viewer_controls.md)

Open **Edit Track** under **Extra tools**, or launch `fisch-trackedit` independently. The editing pipeline step is temporarily hidden.

- Navigate image/mask channels, frames, and Z; use the tracking display and
  length-filter controls to inspect the result. Select up to two tracks for
  editing operations; the viewer's unlimited multi-selection is not used here.
- **Merge Tracks** or **Link histories** for selected tracks.
- **Split Track** from a frame, or **Unlink entire track**.
- **Split Mask** using a local preview; inspect and **Accept split** or
  **Cancel split** before changing the result.
- Enable **Add / edit masks mode**. Supply positive/negative prompts for local
  µSAM prediction, adjust expected cell diameter, and inspect the proposal.
- Correct masks using manual brush/enclosed filling, adjust brush size, and
  change the active/other-mask editing colours.
- **Accept mask**, **Cancel current mask**, **Delete current mask**, or
  **Delete current track**; use Undo for supported edits.
- **Save edited tracking** writes the edited result, including active
  track-length filtering where applicable. In the pipeline, **Use original
  tracking** finishes without adopting an edited result.


The crop/export panel belongs to File Viewer. Rerun measurements after accepting
different masks.

## Editing and saving tracking results

The main GUI temporarily hides the **Edit tracking** pipeline step. Instead,
use **Edit Track** in **Extra tools** beneath the run browser.
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
[tracking TODOs](../../dev/todos.txt) and [micro-SAM cleanup plan](../../dev/microsam_tracking_cleanup.md).

## Measurements after editing

After saving different masks, rerun quantification with overwrite so measurements use the active edited result. Rebuilding a master table alone does not remeasure masks. See [Output tables](../output_tables.md) for track spans, motion, gaps, and repeated rows; see [viewer exports](../viewers.md#exporting-overlays-and-cropping) for annotated TIFFs.
